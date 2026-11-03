import os
import json
import hashlib
import threading
import unicodedata

from dotenv import load_dotenv
from bson.objectid import ObjectId
from pymongo.errors import DuplicateKeyError

from autoe2e.utils import logger

from autoe2e.browser.utils import save_screenshot
from autoe2e.crawler.crawl_context import CrawlContext
from autoe2e.crawler.state import State, StateIdEvaluator
from autoe2e.crawler.action import Action

from autoe2e.llm_api_call import (
    sonnet_chain,
    haiku_chain,
    openai_embeddings
)
from autoe2e.prompts import (
    CONTEXT_EXTRACTION_SYSTEM_PROMPT,
    FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT,
    SIMILARITY_SYSTEM_PROMPT,
    CRITICAL_ACTION_SYSTEM_PROMPT,
    FORM_VALUE_SYSTEM_PROMPT,
    FINALITY_SYSTEM_PROMPT,
    create_context_user_messages,
    create_functionality_user_messages,
    create_similarity_user_messages,
    create_simple_user_messages,
    create_finality_user_messages
)
from autoe2e.utils import (
    png_to_base64,
    extract_response_content,
    geometric_score
)
from autoe2e.mongo_utils import (
    action_func_db,
    func_db
)


load_dotenv()

_functionality_write_lock = threading.Lock()


def _normalized_functionality_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extract_state_context(
    crawl_context: CrawlContext,
    state: State,
    prev_state: State | None = None,
    prev_action: Action | None = None
) -> str:
    state_id = state.get_id(StateIdEvaluator.BY_ACTIONS)
    
    screenshot_path = f'{crawl_context.config.temp_dir}/screenshot_{state_id}.png'
    save_screenshot(crawl_context.driver, screenshot_path)
    logger.info(f'Saved screenshot to {screenshot_path}')
    
    context_text = sonnet_chain(
        CONTEXT_EXTRACTION_SYSTEM_PROMPT,
        create_context_user_messages(
            {
                "description": "None",
                "previous_state": "None. This is the first state." if prev_state is None else prev_state.get_context(),
                "previous_action": "None. This is the first state." if prev_action is None else prev_action.element.outerHTML,
            },
            png_to_base64(screenshot_path)
        )
    )
    
    return context_text


def extract_action_functionalities(
    state: State,
    action: Action,
    prev_action: Action | None = None
) -> list[str]:
    res = sonnet_chain(
        FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT,
        create_functionality_user_messages(
            state.context,
            action.element.outerHTML,
            prev_action.element.outerHTML if prev_action is not None else None
        )
    )

    functionalities = json.loads(extract_response_content(res))

    functionalities = list(map(lambda x: x['feature'], functionalities))

    return functionalities


def extract_action_functionalities_dict(
    state,
    action,
    prev_action = None
) -> list[str]:
    res = sonnet_chain(
        FUNCTIONALITY_EXTRACTION_SYSTEM_PROMPT,
        create_functionality_user_messages(
            state['context'],
            action['outerHTML'],
            prev_action['outerHTML'] if prev_action is not None else None
        )
    )

    functionalities = json.loads(extract_response_content(res))

    functionalities = list(map(lambda x: x['feature'], functionalities))

    return functionalities


def query_similar_functionalities(embedding):
    query = [
        {
            '$vectorSearch': {
                'index': 'vector_index', 
                'path': 'embedding', 
                'queryVector': embedding, 
                'limit': 50,
                'numCandidates': 200
            }
        },
        {
            '$match': {
                'app': os.getenv("APP_NAME"),
            }
        },
        {
            '$limit': 5
        }
    ]

    similar_funcs = list(func_db.aggregate(query))
    return similar_funcs


def get_exact_match_indices(text, similar_funcs):
    indices = []
    
    for i in range(len(similar_funcs)):
        if similar_funcs[i]['text'] == text:
            indices.append(i)
    
    return indices


def map_similar_func_to_exact_match(func_info):
    rank, text, embedding, similar_funcs = func_info
    
    exact_match_indices = get_exact_match_indices(text, similar_funcs)
    
    if len(exact_match_indices) > 0:
        match = {
            'match': True,
            'match_index': exact_match_indices,
            'combined_text': text
        }
    else:
        match = {
            'match': False
        }
    
    if len(similar_funcs) != 0:
        res = sonnet_chain(
            SIMILARITY_SYSTEM_PROMPT,
            create_similarity_user_messages(
                text,
                '\n'.join(map(lambda x: x['text'], similar_funcs))
            )
        )
        
        match = json.loads(extract_response_content(res))
        
        if 'match_index' in match:
            match['match_index'] = list(set(match['match_index'] + exact_match_indices))
        elif len(exact_match_indices) > 0:
            match['match_index'] = exact_match_indices
            match['combined_text'] = text
    
    if match['match']:
        if type(match['match_index']) == int:
            match['match_id'] = [similar_funcs[match['match_index']]['_id']]
        else:
            match['match_id'] = [similar_funcs[m]['_id'] for m in match['match_index']]
    
    match['rank'] = rank
    match['text'] = text
    match['embedding'] = embedding
    
    return match


def no_match_insert(match):
    app_name = os.getenv("APP_NAME")
    text_key = _stable_key(_normalized_functionality_text(match["text"]))
    document = {
        "app": app_name,
        "text": match['text'],
        "text_key": text_key,
        "embedding": match['embedding'],
        "score": geometric_score(match['rank']),
        "final": False,
        "executable": True
    }

    try:
        result = func_db.update_one(
            {"app": app_name, "text_key": text_key},
            {"$setOnInsert": document},
            upsert=True,
        )
    except DuplicateKeyError:
        existing = func_db.find_one({"app": app_name, "text_key": text_key})
        if existing is None:
            raise
        return existing["_id"]

    if result.upserted_id is not None:
        return result.upserted_id

    existing = func_db.find_one({"app": app_name, "text_key": text_key})
    if existing is None:
        raise RuntimeError("Functionality upsert completed without a matching document")
    return existing["_id"]


def match_update(match):
    app_name = os.getenv("APP_NAME")
    primary_id = match["match_id"][0]
    combined_text = match["combined_text"]
    text_key = _stable_key(_normalized_functionality_text(combined_text))
    embedding = openai_embeddings.embed_query(combined_text)
    existing = func_db.find_one({
        "app": app_name,
        "text_key": text_key,
        "_id": {"$ne": primary_id},
    })

    target_id = existing["_id"] if existing is not None else primary_id
    try:
        func_db.update_one(
            {"app": app_name, "_id": target_id},
            {"$set": {
                "text": combined_text,
                "text_key": text_key,
                "embedding": embedding,
            }},
            upsert=False,
        )
    except DuplicateKeyError:
        existing = func_db.find_one({
            "app": app_name,
            "text_key": text_key,
            "_id": {"$ne": target_id},
        })
        if existing is None:
            raise
        target_id = existing["_id"]
        func_db.update_one(
            {"app": app_name, "_id": target_id},
            {"$set": {
                "text": combined_text,
                "embedding": embedding,
            }},
            upsert=False,
        )

    duplicate_ids = [
        functionality_id
        for functionality_id in match["match_id"]
        if functionality_id != target_id
    ]
    if duplicate_ids:
        action_func_db.update_many(
            filter={
                "app": app_name,
                "func_pointer": {"$in": list(map(str, duplicate_ids))},
            },
            update={"$set": {"func_pointer": str(target_id)}},
            upsert=False,
        )
        func_db.delete_many(
            {
                "app": app_name,
                "_id": {"$in": duplicate_ids},
            }
        )

    return target_id


def update_databases_with_match(match):
    if match['match']:
        return match_update(match)
    return no_match_insert(match)


def insert_functionalities(functionalities: list[str]):
    embeddings = openai_embeddings.embed_documents(functionalities)
    insertion_ids = []

    for rank, (text, embedding) in enumerate(zip(functionalities, embeddings)):
        with _functionality_write_lock:
            similar_funcs = query_similar_functionalities(embedding)
            match = map_similar_func_to_exact_match(
                (rank, text, embedding, similar_funcs)
            )
            insertion_ids.append(update_databases_with_match(match))

    return insertion_ids


def insert_action_functionality(
    func_ids: list,
    state_id: str,
    state_url: str,
    prev_state_id: str,
    action_id: str,
    prev_action_id: str,
    action_test_id: str,
    action_depth: int,
    action_type: str = "SINGLE"
):
    app_name = os.getenv("APP_NAME")

    for index, func_id in enumerate(func_ids):
        document = {
            "app": app_name,
            "url": state_url,
            "state": state_id,
            "prev_state": prev_state_id,
            "action": action_id,
            "prev_action": prev_action_id,
            "test_id": action_test_id,
            "depth": action_depth,
            "type": action_type,
            "rank_score": geometric_score(index),
            "func_pointer": str(func_id),
            "final": False,
            "should_execute": True
        }
        relation_identity = json.dumps(
            [
                app_name,
                state_id,
                prev_state_id,
                action_id,
                prev_action_id,
                str(func_id),
                action_type,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        document["dedupe_key"] = _stable_key(relation_identity)

        try:
            action_func_db.update_one(
                {"app": app_name, "dedupe_key": document["dedupe_key"]},
                {"$setOnInsert": document},
                upsert=True,
            )
        except DuplicateKeyError:
            if action_func_db.find_one({
                "app": app_name,
                "dedupe_key": document["dedupe_key"],
            }) is None:
                raise


def update_functionality_score(prev_state, prev_action, curr_state, curr_action):
    curr_action_funcs = list(action_func_db.find({
        'app': os.getenv("APP_NAME"),
        'state': curr_state.get_id(StateIdEvaluator.BY_ACTIONS),
        'action': curr_action.get_id(),
        'type': 'DOUBLE'
    }))
    
    prev_action_funcs = list(action_func_db.find({
        'app': os.getenv("APP_NAME"),
        'state': prev_state.get_id(StateIdEvaluator.BY_ACTIONS),
        'action': prev_action.get_id(),
        'type': 'SINGLE'
    }))
    
    func_score_updates = {}
    
    for curr_func in curr_action_funcs:
        corresponding_func_in_prev = list(filter(lambda x: x['func_pointer'] == curr_func['func_pointer'], prev_action_funcs))
        prev_score = geometric_score(None) if len(corresponding_func_in_prev) == 0 \
            else corresponding_func_in_prev[0]['rank_score']
        diff = curr_func['rank_score'] - prev_score
        func_score_updates[curr_func['func_pointer']] = diff
    
    for _id, diff in func_score_updates.items():
        func_db.update_one(
            filter={
                'app': os.getenv("APP_NAME"),
                '_id': ObjectId(_id),
                'final': False
            },
            update={
                '$inc': {
                    'score': diff
                }
            },
            upsert=False
        )


def update_functionality_score_dict(prev_state, prev_action, curr_state, curr_action):
    curr_action_funcs = list(action_func_db.find({
        'app': os.getenv("APP_NAME"),
        'state': curr_state['id'],
        'action': curr_action['id'],
        'type': 'DOUBLE'
    }))
    
    prev_action_funcs = list(action_func_db.find({
        'app': os.getenv("APP_NAME"),
        'state': prev_state['id'],
        'action': prev_action['id'],
        'type': 'SINGLE'
    }))
    
    func_score_updates = {}
    
    for curr_func in curr_action_funcs:
        corresponding_func_in_prev = list(filter(lambda x: x['func_pointer'] == curr_func['func_pointer'], prev_action_funcs))
        prev_score = geometric_score(None) if len(corresponding_func_in_prev) == 0 \
            else corresponding_func_in_prev[0]['rank_score']
        diff = curr_func['rank_score'] - prev_score
        func_score_updates[curr_func['func_pointer']] = diff
    
    for _id, diff in func_score_updates.items():
        func_db.update_one(
            filter={
                'app': os.getenv("APP_NAME"),
                '_id': ObjectId(_id),
                'final': False
            },
            update={
                '$inc': {
                    'score': diff
                }
            },
            upsert=False
        )



def mark_final_functionalities(curr_state, curr_action):
    curr_action_funcs = list(action_func_db.find({
        'app': os.getenv("APP_NAME"),
        'state': curr_state.get_id(StateIdEvaluator.BY_ACTIONS),
        'action': curr_action.get_id(),
    }))
    retreived_funcs = list(func_db.find({
        'app': { '$eq': os.getenv("APP_NAME") },
        '_id': {
            '$in': list(map(lambda x: ObjectId(x['func_pointer']), curr_action_funcs))
        }
    }))

    if len(retreived_funcs) == 0:
        return
    
    res = sonnet_chain(
        FINALITY_SYSTEM_PROMPT,
        create_finality_user_messages(
            curr_state.context,
            curr_action.element.outerHTML,
            '\n'.join(map(lambda x: x['text'], retreived_funcs))
        )
    )

    finality = eval(extract_response_content(res))

    for i in range(len(finality)):
        if finality[i]:
            func_db.update_one(
                filter={
                    'app': os.getenv("APP_NAME"),
                    '_id': retreived_funcs[i]['_id']
                },
                update={
                    '$set': {
                        'final': True,
                    }
                },
                upsert=False
            )


def mark_final_functionalities_dict(curr_state, curr_action):
    curr_action_funcs = list(action_func_db.find({
        'app': os.getenv("APP_NAME"),
        'state': curr_state['id'],
        'action': curr_action['id'],
    }))
    retreived_funcs = list(func_db.find({
        'app': { '$eq': os.getenv("APP_NAME") },
        '_id': {
            '$in': list(map(lambda x: ObjectId(x['func_pointer']), curr_action_funcs))
        }
    }))

    if len(retreived_funcs) == 0:
        return
    
    res = sonnet_chain(
        FINALITY_SYSTEM_PROMPT,
        create_finality_user_messages(
            curr_state['context'],
            curr_action['outerHTML'],
            '\n'.join(map(lambda x: x['text'], retreived_funcs))
        )
    )

    finality = eval(extract_response_content(res))

    for i in range(len(finality)):
        if finality[i]:
            func_db.update_one(
                filter={
                    'app': os.getenv("APP_NAME"),
                    '_id': retreived_funcs[i]['_id']
                },
                update={
                    '$set': {
                        'final': True,
                    }
                },
                upsert=False
            )
            action_func_db.update_many(
                filter={
                    'app': os.getenv("APP_NAME"),
                    'func_pointer': str(retreived_funcs[i]['_id']),
                    'action': curr_action['id'],
                    'state': curr_state['id']
                },
                update={
                    '$set': {
                        'final': True
                    }
                },
                upsert=False
            )


def is_action_critical(action: Action) -> bool:
    element_html = action.get_element().outerHTML

    res = haiku_chain(
        CRITICAL_ACTION_SYSTEM_PROMPT,
        create_simple_user_messages(element_html)
    )

    return eval(res)


def create_form_filling_values(action: Action):
    element_html = action.get_element().outerHTML

    res = sonnet_chain(
        FORM_VALUE_SYSTEM_PROMPT,
        create_simple_user_messages(element_html)
    )

    return json.loads(res)
