import argparse
import json
import os
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

from functionality_labels import canonicalize_functionality


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def route_label(url: str) -> str:
    path = url.split("?", 1)[0].rstrip("/").split("/petclinic", 1)[-1].strip("/")
    labels = {
        "welcome": "Início",
        "owners": "Proprietários",
        "vets": "Veterinários",
        "pettypes": "Tipos de pets",
        "specialties": "Especialidades",
        "add": "Novo",
        "edit": "Edição",
    }
    if not path:
        return "Início"
    return " / ".join(
        labels.get(part.lower(), part.replace("-", " ").title())
        for part in path.split("/")
    )


def action_label(action: dict) -> str:
    test_id = action.get("testId") or ""
    labels = {
        "c1-navbar-home": "Início",
        "c2-navbar-owners": "Proprietários (abrir menu)",
        "c3-navbar-owners-search": "Pesquisar proprietários",
        "c4-navbar-owners-add-new": "Novo proprietário",
        "c5-navbar-vets": "Veterinários (abrir menu)",
        "c6-navbar-vets-all": "Todos os veterinários",
        "c7-navbar-vets-add-new": "Novo veterinário",
        "c8-navbar-pet-types": "Tipos de pets",
        "c9-navbar-specialties": "Especialidades",
    }
    if test_id in labels:
        return labels[test_id]
    extractor = TextExtractor()
    extractor.feed(action.get("outerHTML") or "")
    return " ".join(extractor.parts)[:100] or test_id or "Ação registrada"


def load_functionality_data(report_path: Path) -> dict:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    nodes = report.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValueError(f"{report_path} does not contain any states")

    load_dotenv()
    client = MongoClient(os.getenv("ATLAS_URI"), serverSelectionTimeoutMS=10000)
    try:
        db = client.myDatabase
        functions = list(
            db.functionality.find(
                {"app": "PETCLINIC", "final": True}, {"text": 1, "_id": 1}
            )
        )
        function_text = {
            str(item["_id"]): item.get("text", "").strip()
            for item in functions
            if item.get("text")
        }
        relations = list(
            db["action-functionality"].find(
                {
                    "app": "PETCLINIC",
                    "func_pointer": {"$in": list(function_text)},
                },
                {"func_pointer": 1, "state": 1, "action": 1, "_id": 0},
            )
        )
    finally:
        client.close()

    children: dict[str, list[str]] = defaultdict(list)
    for state_id, state in nodes.items():
        parent_id = state.get("prev_state")
        if parent_id in (None, "", "None"):
            continue
        if parent_id not in nodes:
            raise ValueError(f"State {state_id} refers to missing parent {parent_id}")
        children[parent_id].append(state_id)

    grouped: dict[tuple[str, str], dict] = {}
    for relation in relations:
        raw_name = function_text.get(relation.get("func_pointer"))
        source_id = relation.get("state")
        action_id = relation.get("action")
        if not raw_name or source_id not in nodes:
            continue

        source = nodes[source_id]
        action = next(
            (
                item
                for item in source.get("actions", [])
                if item.get("id") == action_id
            ),
            None,
        )
        if action is None:
            continue

        targets = [
            target_id
            for target_id in children[source_id]
            if nodes[target_id].get("prev_action") == action_id
        ]
        if not targets:
            continue

        route = " ".join(
            [source.get("url", "")]
            + [nodes[target_id].get("url", "") for target_id in targets]
        )
        category, canonical_name = canonicalize_functionality(
            raw_name, action.get("testId"), route
        )
        key = (category, canonical_name)
        feature = grouped.setdefault(
            key,
            {"category": category, "name": canonical_name, "original_names": set(), "paths": {}},
        )
        feature["original_names"].add(raw_name)

        chain = []
        current_id = source_id
        while current_id:
            chain.append(current_id)
            parent_id = nodes[current_id].get("prev_state")
            current_id = parent_id if parent_id and parent_id != "None" else None
        chain.reverse()

        steps = []
        for index, state_id in enumerate(chain):
            state = nodes[state_id]
            transition = None
            if index:
                parent = nodes[chain[index - 1]]
                previous_action_id = state.get("prev_action")
                previous_action = next(
                    (
                        item
                        for item in parent.get("actions", [])
                        if item.get("id") == previous_action_id
                    ),
                    None,
                )
                if previous_action is None:
                    raise ValueError(
                        f"Cannot find entering action for state {state_id}"
                    )
                transition = {
                    "name": action_label(previous_action),
                    "test_id": previous_action.get("testId") or "",
                }
            steps.append(
                {
                    "route": route_label(state.get("url", "")),
                    "url": state.get("url", ""),
                    "transition": transition,
                }
            )

        for target_id in targets:
            target = nodes[target_id]
            path = {
                "steps": steps,
                "action": action_label(action),
                "test_id": action.get("testId") or "",
                "target": {
                    "route": route_label(target.get("url", "")),
                    "url": target.get("url", ""),
                },
            }
            path_key = (
                tuple(step["url"] for step in steps),
                tuple(
                    step["transition"]["test_id"]
                    for step in steps
                    if step["transition"]
                ),
                path["test_id"],
                target.get("url", ""),
            )
            feature["paths"][path_key] = path

    return {
        "features": [
            {
                **feature,
                "original_names": sorted(feature["original_names"], key=str.casefold),
                "paths": list(feature["paths"].values()),
            }
            for feature in sorted(
                grouped.values(),
                key=lambda item: (item["category"], item["name"].casefold()),
            )
        ],
        "state_count": len(nodes),
        "transition_count": sum(map(len, children.values())),
    }


HTML_TEMPLATE = r"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Funcionalidades e caminhos — PETCLINIC</title>
<style>
:root{color-scheme:light;--ink:#17243a;--muted:#586a81;--nav:#173d61;--line:#cbd6e2;--bg:#f4f7fb;--card:#fff;--blue:#2266a8;--bluebg:#edf6ff;--green:#26704d;--greenbg:#eaf8f0;--gold:#805800;--goldbg:#fff5d8}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}header{background:var(--nav);color:#fff;padding:22px max(18px,calc((100vw - 1180px)/2))}h1{font-size:clamp(23px,3vw,32px);line-height:1.15;margin:0 0 7px}header p{margin:0;color:#d6e6f4}.layout{max-width:1180px;margin:20px auto;padding:0 16px;display:grid;grid-template-columns:340px minmax(0,1fr);gap:18px;align-items:start}.left,.right{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 3px 14px #1434510a}.left{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto;padding:16px}.right{min-height:360px;padding:22px}.explain{background:#eaf3fb;border-radius:9px;padding:12px;font-size:14px;color:#31465f;margin-bottom:12px}.summary{font-size:12px;color:var(--muted);margin:8px 0 12px}.search{width:100%;padding:10px;border:1px solid #aebccd;border-radius:8px;font:inherit}.group{margin-top:15px}.group h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 5px}.item{display:block;width:100%;text-align:left;background:#fff;border:1px solid transparent;border-radius:7px;padding:8px 9px;margin:2px 0;color:var(--ink);font:inherit;cursor:pointer}.item:hover,.item.active{background:#edf6ff;border-color:#9fc4e5;color:#134e7e}.item small{display:block;color:var(--muted);font-size:11px}.title{margin:0;font-size:24px}.notice{background:var(--goldbg);border-left:4px solid #d6a440;border-radius:5px;padding:11px 13px;margin:15px 0;font-size:13px}.path{border:1px solid var(--line);border-radius:11px;margin:10px 0 15px;overflow:hidden}.path-head{padding:9px 12px;background:#f0f3f7;font-size:12px;color:var(--muted)}.steps{padding:13px}.step{border:1px solid #a9c5df;background:var(--bluebg);border-radius:9px;padding:10px 12px}.step.start{background:var(--greenbg);border-color:#9cc8a9}.step.target{background:var(--goldbg);border-color:#d6ba68}.step b{display:block}.step small{display:block;color:var(--muted);overflow-wrap:anywhere}.arrow{text-align:center;color:var(--blue);font-size:13px;font-weight:700;padding:5px}.arrow span{background:#fff;border:1px solid var(--line);border-radius:20px;padding:3px 9px;display:inline-block}.final-action{background:#fff7e2;border:2px solid #d6ba68;border-radius:9px;padding:10px 12px;margin:8px 0}.originals{font-size:13px;color:var(--muted);margin:12px 0}.originals summary{cursor:pointer}.foot{max-width:1180px;margin:0 auto 24px;padding:0 16px;color:var(--muted);font-size:12px}@media(max-width:820px){.layout{grid-template-columns:1fr}.left{position:static;max-height:45vh}.right{padding:16px}}
</style></head><body>
<header><h1>Funcionalidades do PetClinic: o que clicar para chegar?</h1><p>Nomes semelhantes foram agrupados. Selecione uma funcionalidade para ver os passos.</p></header>
<div class="layout"><aside class="left"><div class="explain"><b>Como usar:</b><br>1. Escolha um nome da lista.<br>2. Siga os cliques desde o início.<br>3. A caixa amarela mostra a ação associada.<br><br>Menus são passos de navegação, não objetivos finais.</div><input class="search" id="search" placeholder="Filtrar funcionalidades..."><div class="summary" id="summary"></div><nav id="list"></nav></aside><main class="right" id="result"><h2>Escolha uma funcionalidade</h2><p>O mapa mostra o caminho registrado e a ação associada.</p></main></div>
<div class="foot" id="foot"></div><script id="mapdata" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('mapdata').textContent),list=document.getElementById('list'),result=document.getElementById('result'),search=document.getElementById('search');
const groupOrder=['Proprietários','Veterinários','Tipos de pets','Especialidades','Navegação','Validações','Outras'];
document.getElementById('summary').textContent=`${data.features.length} funcionalidades agrupadas · ${data.transition_count} transições · ${data.state_count} estados`;
document.getElementById('foot').textContent='Fonte: último report/PETCLINIC.json e funcionalidades registradas para PETCLINIC. Os nomes originais são preservados abaixo de cada grupo. Chegar a um formulário não confirma que o cadastro foi salvo.';
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
let selected='';function renderList(query=''){list.innerHTML='';for(const group of groupOrder){const items=data.features.filter(f=>f.category===group&&(`${f.name} ${f.original_names.join(' ')}`.toLowerCase().includes(query.toLowerCase())));if(!items.length)continue;const section=document.createElement('section');section.className='group';section.innerHTML=`<h2>${esc(group)} (${items.length})</h2>`;for(const f of items){const button=document.createElement('button');button.className='item'+(selected===f.name?' active':'');button.innerHTML=`${esc(f.name)}<small>${f.paths.length} caminho(s) associado(s)</small>`;button.onclick=()=>show(f.name);section.appendChild(button)}list.appendChild(section)}}
function renderPath(path,index,total){let out=`<section class="path"><div class="path-head">Caminho ${index+1} de ${total}</div><div class="steps">`;path.steps.forEach((step,i)=>{out+=`<div class="step ${i===0?'start':''}"><b>${i===0?'INÍCIO':'TELA'}: ${esc(step.route)}</b><small>${esc(step.url)}</small></div>`;if(i+1<path.steps.length){const next=path.steps[i+1];out+=`<div class="arrow"><span>clique em: ${esc(next.transition?.name||'Ação')}</span>${next.transition?.test_id?`<br><small>${esc(next.transition.test_id)}</small>`:''}</div>`}});out+=`<div class="final-action"><b>AÇÃO ASSOCIADA: ${esc(path.action)}</b>${path.test_id?`<small>Identificador: ${esc(path.test_id)}</small>`:''}</div><div class="arrow"><span>tela alcançada ↓</span></div><div class="step target"><b>${esc(path.target.route)}</b><small>${esc(path.target.url)}</small></div></div></section>`;return out}
function show(name){selected=name;const feature=data.features.find(f=>f.name===name);if(!feature)return;renderList(search.value);const originals=feature.original_names.map(x=>`<li>${esc(x)}</li>`).join('');result.innerHTML=`<h2 class="title">${esc(feature.name)}</h2><div class="notice">Nomes semelhantes agrupados por intenção e ação observada. Abrir um menu é um passo de navegação; a funcionalidade final é mostrada separadamente. A análise não confirma que um cadastro/edição foi salvo.</div><details class="originals"><summary>Ver ${feature.original_names.length} nome(s) original(is) preservado(s) do Gemini</summary><ul>${originals}</ul></details><h3>${feature.paths.length} caminho(s) de ação</h3>${feature.paths.map((path,index)=>renderPath(path,index,feature.paths.length)).join('')}`}
search.addEventListener('input',()=>renderList(search.value));renderList();
</script></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a PETCLINIC functionality map with similar names grouped."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("report/PETCLINIC.json"),
        help="Path to the crawler JSON report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("report/PETCLINIC_funcionalidades-caminhos.html"),
        help="Output HTML path",
    )
    args = parser.parse_args()
    data = load_functionality_data(args.report)
    embedded_data = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = HTML_TEMPLATE.replace("__DATA__", embedded_data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(page, encoding="utf-8")
    print(
        f"Mapa salvo em {args.output}: {len(data['features'])} nomes agrupados, "
        f"{sum(len(feature['paths']) for feature in data['features'])} caminhos."
    )


if __name__ == "__main__":
    main()
