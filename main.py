import os
import time
import json
from concurrent.futures import ThreadPoolExecutor

from autoe2e.utils import *
from autoe2e.init_utils import *
from autoe2e.infer_utils import *
from autoe2e.loop_utils import *
from autoe2e.mongo_utils import *
from autoe2e.manual_ndd import *

APP_NAME = os.getenv('APP_NAME', 'PETCLINIC')
run_started_at = time.perf_counter()
llm_worker_count = int(os.getenv("AUTOE2E_LLM_WORKERS", "4"))
if llm_worker_count < 1:
    raise ValueError("AUTOE2E_LLM_WORKERS must be at least 1")

# Limpeza inicial do banco
ensure_deduplication_indexes()
action_func_db.delete_many({'app': APP_NAME})
func_db.delete_many({'app': APP_NAME})

# Configuração e inicialização do contexto
crawl_context: CrawlContext = CrawlContext()
crawl_context = crawl_context.set_temp_var('config_path', f'./configs/{APP_NAME}.json')

config: dict = read_config(config_path=crawl_context.temp_vars.get('config_path', None))
config_obj: Config = Config.from_dict(config)

if config_obj.base_url is None:
    raise ValueError('base_url is required in config')

crawl_context = crawl_context.set_config(config_obj)
driver = initialize_driver(config_obj)
crawl_context = crawl_context.set_driver(driver)
crawl_context = initialize_variables(crawl_context)

LOOP_COUNTER = 0

# Pool de threads para processar chamadas de LLM e I/O de banco em segundo plano
llm_executor = ThreadPoolExecutor(max_workers=llm_worker_count)
analysis_futures = []

def process_action_analysis_async(current_state: State, action: Action, state: State):
    """Executa a análise de funcionalidades e gravações no MongoDB sem travar o WebDriver."""
    try:
        # 1. Análise de cenário simples
        functionalities = extract_action_functionalities(current_state, action)
        if functionalities:
            functionality_ids = insert_functionalities(functionalities)
            insert_action_functionality(
                func_ids=functionality_ids,
                state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                state_url=state.url,
                prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                action_id=action.get_id(),
                prev_action_id=state.crawl_path.get_action(-1).get_id() if len(state.crawl_path) > 0 else None,
                action_test_id=action.element.test_id,
                action_depth=len(state.crawl_path),
                action_type="SINGLE"
            )

        # 2. Análise de cenário duplo (Double Action)
        if len(current_state.crawl_path) > 0:
            prev_action = current_state.crawl_path.get_action(-1)
            double_functionalities = extract_action_functionalities(current_state, action, prev_action)
            if double_functionalities:
                d_func_ids = insert_functionalities(double_functionalities)
                insert_action_functionality(
                    func_ids=d_func_ids,
                    state_id=state.get_id(StateIdEvaluator.BY_ACTIONS),
                    state_url=state.url,
                    prev_state_id=state.crawl_path.get_state(-1).get_id(StateIdEvaluator.BY_ACTIONS) if len(state.crawl_path) > 0 else None,
                    action_id=action.get_id(),
                    prev_action_id=prev_action.get_id() if len(state.crawl_path) > 0 else None,
                    action_test_id=action.element.test_id,
                    action_depth=len(state.crawl_path),
                    action_type="DOUBLE"
                )

            update_functionality_score(
                current_state.crawl_path.get_state(-1),
                current_state.crawl_path.get_action(-1),
                current_state,
                action
            )

        # 3. Marcação final
        mark_final_functionalities(current_state, action)
    except Exception as e:
        logger.error(f"Erro na análise assíncrona da ação {action.get_id()}: {e}")
        raise

# Loop principal de crawling
while len(crawl_context.crawl_stack) > 0:
    state: State = crawl_context.crawl_stack.pop()
    logger.info(
        f"DFS visiting depth={len(state.crawl_path)} "
        f"state={state.get_id(StateIdEvaluator.BY_ACTIONS)} "
        f"pending={len(crawl_context.crawl_stack)}"
    )
    crawl_context.state_machine.set_current_state(state)
    
    current_state: State = crawl_context.state_machine.get_current_state()
    current_actions: list[Action] = current_state.get_actions()

    crawl_context.load_state(current_state)

    logger.info('Extracting state context using LLM')
    state_context = extract_state_context(
        crawl_context,
        current_state,
        current_state.crawl_path.get_state(-1) if len(current_state.crawl_path) > 0 else None,
        current_state.crawl_path.get_action(-1) if len(current_state.crawl_path) > 0 else None,
    )
    current_state.set_context(state_context)

    # Conjunto para filtrar ações redundantes no mesmo estado (ex: múltiplos botões idênticos)
    processed_action_signatures = set()

    for action in current_actions:
        LOOP_COUNTER += 1
        
        # Filtro direcionado: evita reprocessar seletores idênticos no mesmo estado
        action_signature = (action.get_type().get_value(), action.element.tag_name, action.element.test_id)
        if action_signature in processed_action_signatures:
            continue
        processed_action_signatures.add(action_signature)

        should_extract_func = True
        state_modified = False

        is_critical = is_action_critical(action)
        
        if not is_critical:
            if action.get_type().get_value() == 'form':
                values = create_form_filling_values(action)
                action.set_params(values)
            
            crawl_context.execute_action(action)
            state_modified = True

            # Extração de ações candidatas otimizada com menos retries cegos
            new_actions = []
            for _ in range(5):
                try:
                    new_actions = CandidateActionExtractor.extract_candidate_actions(crawl_context.driver)
                    if new_actions:
                        break
                except Exception:
                    time.sleep(0.05)

            if len(new_actions) == 0:
                logger.warning(f"Nenhuma nova ação detectada após executar {action.get_id()}")
            else:
                new_state: State = crawl_context.create_state_from_driver(new_actions)
                if not is_state_in_graph(crawl_context, new_state):
                    logger.info(
                        f"DFS discovered state={new_state.get_id(StateIdEvaluator.BY_ACTIONS)} "
                        f"from action={action.get_id()}"
                    )
                    crawl_context.crawl_stack.push(new_state)
                    crawl_context.state_machine.add_state_from_current_state(new_state, action)
                    logger.info(
                        f"DFS pushed state; pending={len(crawl_context.crawl_stack)}"
                    )
                else:
                    should_extract_func = False

        if should_extract_func:
            # Envia a análise para o pool assíncrono para liberar o WebDriver imediatamente
            analysis_futures.append(
                llm_executor.submit(
                    process_action_analysis_async, current_state, action, state
                )
            )

        # OTIMIZAÇÃO CRÍTICA: Só recarrega o estado via browser se o DOM/URL tiver sido modificado
        if state_modified:
            crawl_context.load_state(crawl_context.state_machine.get_current_state())

# Aguarda conclusão de todas as análises pendentes da LLM antes de fechar o driver e salvar
llm_executor.shutdown(wait=True)
crawl_context.driver.quit()
for analysis_future in analysis_futures:
    analysis_future.result()

# Geração final do relatório JSON
states_converted = {}
for state_id, state_obj in crawl_context.state_machine.state_graph.states.items():
    states_converted[state_id] = {
        'url': state_obj.url,
        'context': state_obj.context,
        'actions': [{
                'type': a.action_type.get_value(),
                'id': a.element.get_id(),
                'outerHTML': clean_children_html(a.element.outerHTML),
                'testId': a.element.test_id
            } for a in state_obj.get_actions()
        ],
        'prev_state': state_obj.crawl_path.get_state(-1).get_id() if len(state_obj.crawl_path) > 0 else None,
        'prev_action': state_obj.crawl_path.get_action(-1).get_id() if len(state_obj.crawl_path) > 0 else None,
    }

adj_list_converted = {}
for state_id, neighbor_list in crawl_context.state_machine.state_graph.adjacency_list.items():
    adj_list_converted[state_id] = {
        action_obj.get_id(): n_state_id for action_obj, n_state_id in neighbor_list.items()
    }

os.makedirs('./report', exist_ok=True)
with open(f'./report/{APP_NAME}.json', 'w+') as f:
    json.dump({
        'nodes': states_converted,
        'edges': adj_list_converted
    }, f)

logger.info(
    f"Crawling concluído em {time.perf_counter() - run_started_at:.2f}s "
    f"com {llm_worker_count} worker(s) de LLM"
)