import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def action_label(parent: dict, state: dict) -> str:
    action_id = state.get("prev_action")
    for action in parent.get("actions", []):
        if action.get("id") != action_id:
            continue

        test_id = action.get("testId") or ""
        if test_id:
            label = re.sub(r"^[ct]\d+-", "", test_id)
            label = re.sub(r"^navbar-", "", label)
            words = label.replace("-", " ").split()
            replacements = {
                "owner": "Owner",
                "owners": "Owners",
                "vet": "Veterinarian",
                "vets": "Veterinarians",
                "pettype": "Pet Type",
                "pettypes": "Pet Types",
                "specialty": "Specialty",
                "specialties": "Specialties",
            }
            return " ".join(replacements.get(word.lower(), word.title()) for word in words)

        extractor = TextExtractor()
        extractor.feed(action.get("outerHTML", ""))
        if extractor.parts:
            return " ".join(extractor.parts)

    return "Action"


def route_label(url: str) -> str:
    path = url.split("?", 1)[0].rstrip("/")
    route = path.rsplit("/petclinic", 1)[-1].strip("/")
    if not route or route == "welcome":
        return "Home"

    labels = {
        "owners": "Owners",
        "vets": "Veterinarians",
        "pettypes": "Pet Types",
        "specialties": "Specialties",
    }
    parts = route.split("/")
    return " / ".join(
        labels.get(part.lower(), part.replace("-", " ").title()) for part in parts
    )


def build_tree(report: dict) -> tuple[dict, list[dict]]:
    source_nodes = report.get("nodes")
    if not isinstance(source_nodes, dict) or not source_nodes:
        raise ValueError("Report must contain a non-empty 'nodes' object")

    nodes = {
        state_id: {
            "id": state_id,
            "state": state,
            "children": [],
            "depth": 0,
            "route": route_label(state.get("url", "")),
        }
        for state_id, state in source_nodes.items()
    }
    roots = []

    for node in nodes.values():
        parent_id = node["state"].get("prev_state")
        if parent_id in (None, "None"):
            roots.append(node)
            continue
        parent = nodes.get(parent_id)
        if parent is None:
            raise ValueError(f"State {node['id']} refers to missing parent {parent_id}")
        node["parent"] = parent
        node["action"] = action_label(parent["state"], node["state"])
        parent["children"].append(node)

    if len(roots) != 1:
        raise ValueError(f"Expected one initial state, found {len(roots)}")

    visited = set()

    def order_children(node: dict, depth: int) -> None:
        if node["id"] in visited:
            raise ValueError("State parent references contain a cycle")
        visited.add(node["id"])
        node["depth"] = depth
        action_order = {
            action.get("id"): index
            for index, action in enumerate(node["state"].get("actions", []))
        }
        node["children"].sort(
            key=lambda child: action_order.get(
                child["state"].get("prev_action"), len(action_order)
            )
        )
        for child in node["children"]:
            order_children(child, depth + 1)

    order_children(roots[0], 0)
    if len(visited) != len(nodes):
        raise ValueError("Some states are disconnected from the initial state")

    return roots[0], list(nodes.values())


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoE2E report tree</title>
<style>
:root{color-scheme:dark;--bg:#0b1220;--panel:#111c2f;--border:#253650;--text:#e7eefb;--muted:#9aabc3;--accent:#65b8ff;--green:#43c59e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
header{display:flex;align-items:center;gap:14px;padding:12px 18px;border-bottom:1px solid var(--border);background:#101a2b}
h1{font-size:17px;margin:0;white-space:nowrap}#summary{color:var(--muted);font-size:12px}
main{display:grid;grid-template-columns:minmax(0,1fr) 310px;height:calc(100vh - 57px)}
#canvas{position:relative;overflow:hidden;min-width:0;background-image:radial-gradient(#253650 1px,transparent 1px);background-size:22px 22px}
svg{display:block;width:100%;height:100%;touch-action:none;user-select:none}
.toolbar{position:absolute;z-index:2;top:12px;left:12px;display:flex;gap:6px;align-items:center;padding:8px;background:#111c2feF;border:1px solid var(--border);border-radius:10px;box-shadow:0 6px 24px #0005}
button,input{font:inherit;color:var(--text);background:#17253a;border:1px solid #344964;border-radius:6px;padding:7px 10px}
button{cursor:pointer}button:hover{border-color:var(--accent)}input{width:min(270px,28vw)}input::placeholder{color:#93a6c0}
aside{overflow:auto;padding:18px;border-left:1px solid var(--border);background:var(--panel)}
aside h2{margin:0 0 8px;font-size:17px}aside h3{margin:20px 0 5px;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}
aside p{margin:0;color:#d4deed;overflow-wrap:anywhere}#hint{color:var(--muted)}
.tree-link{fill:none;stroke:#506985;stroke-width:2}.tree-link.is-path{stroke:var(--accent);stroke-width:3}
.node{cursor:pointer}.node rect{fill:#15243a;stroke:#425c7a;stroke-width:1.5;rx:12}
.node:hover rect,.node.selected rect{stroke:var(--accent);stroke-width:2.5}.node.root rect{fill:#12352f;stroke:var(--green)}
.node.search-hit rect{stroke:#f3c969;stroke-width:3}.node.search-muted{opacity:.2}
.node .route{fill:var(--text);font-size:13px;font-weight:650}.node .action{fill:#9db1cb;font-size:10px}
.node .depth{fill:#7f93ad;font-size:9px}
@media(max-width:850px){main{grid-template-columns:1fr;height:auto;min-height:calc(100vh - 57px)}#canvas{height:65vh;min-height:430px}aside{border-left:0;border-top:1px solid var(--border)}header{flex-wrap:wrap}.toolbar{flex-wrap:wrap}.toolbar input{width:150px}}
</style>
</head>
<body>
<header><h1>AutoE2E · <span id="app-name"></span></h1><div id="summary"></div></header>
<main>
<section id="canvas" aria-label="Interactive state tree">
  <div class="toolbar">
    <input id="search" type="search" placeholder="Search states or actions…" aria-label="Search">
    <button id="fit">Fit</button><button id="focus">Focus branch</button>
    <button id="zoom-in" aria-label="Zoom in">+</button><button id="zoom-out" aria-label="Zoom out">−</button>
  </div>
  <svg id="graph" role="img" aria-label="State transition tree">
    <g id="viewport"><g id="links"></g><g id="nodes"></g></g>
  </svg>
</section>
<aside>
  <h2 id="detail-title">Select a state</h2>
  <p id="hint">Click a node to inspect its URL, context, and available actions.</p>
  <div id="details" hidden>
    <h3>State</h3><p id="state-id"></p>
    <h3>URL</h3><p id="state-url"></p>
    <h3>Depth</h3><p id="state-depth"></p>
    <h3>Entered by</h3><p id="state-action"></p>
    <h3>Context</h3><p id="state-context"></p>
    <h3>Available actions</h3><p id="state-actions"></p>
  </div>
</aside>
</main>
<script id="report-data" type="application/json">__REPORT_JSON__</script>
<script>
const report = JSON.parse(document.getElementById("report-data").textContent);
const NS = "http://www.w3.org/2000/svg";
const rootId = Object.keys(report.nodes).find(id => !report.nodes[id].prev_state || report.nodes[id].prev_state === "None");
const children = new Map(Object.keys(report.nodes).map(id => [id, []]));
for (const [id, state] of Object.entries(report.nodes)) {
  if (state.prev_state && state.prev_state !== "None") children.get(state.prev_state)?.push(id);
}
for (const ids of children.values()) ids.sort((a,b) => {
  const pa=report.nodes[a], pb=report.nodes[b], actions=report.nodes[pa.prev_state]?.actions||[];
  return actions.findIndex(x=>x.id===pa.prev_action)-actions.findIndex(x=>x.id===pb.prev_action);
});
const depth = new Map();
const visibleRoot = rootId;
const cardW=208, cardH=86, colGap=248, rowGap=146, marginX=34, marginY=76;
let leaf=0, maxDepth=0;
const positions=new Map();
function layout(id,d=0){
  depth.set(id,d);maxDepth=Math.max(maxDepth,d);
  const kids=children.get(id)||[];
  if(!kids.length){const x=marginX+leaf++*colGap;positions.set(id,{x,y:marginY+d*rowGap});return x;}
  const xs=kids.map(k=>layout(k,d+1)),x=(xs[0]+xs[xs.length-1])/2;
  positions.set(id,{x,y:marginY+d*rowGap});return x;
}
layout(visibleRoot);
const width=Math.max(1100,marginX*2+Math.max(1,leaf-1)*colGap+cardW);
const height=marginY*2+maxDepth*rowGap+cardH;
const svg=document.getElementById("graph"), viewport=document.getElementById("viewport");
svg.setAttribute("viewBox",`0 0 ${width} ${height}`);
const make=(tag,attrs={})=>{const el=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);return el;};
const links=document.getElementById("links"), nodeLayer=document.getElementById("nodes");
function actionFor(id){
  const state=report.nodes[id],parent=report.nodes[state.prev_state];
  if(!parent)return "Initial state";
  const action=parent.actions?.find(a=>a.id===state.prev_action);
  if(!action)return "Action";
  if(action.testId)return action.testId.replace(/^[ct]\d+-/,"").replace(/^navbar-/,"").replaceAll("-"," ");
  const text=(action.outerHTML||"").replace(/<[^>]*>/g," ").replace(/\s+/g," ").trim();
  return text||"Action";
}
function descendants(id,out=[]){out.push(id);for(const child of children.get(id)||[])descendants(child,out);return out;}
function renderLinks(id){
  const p=positions.get(id);
  for(const childId of children.get(id)||[]){
    const c=positions.get(childId),sx=p.x,sy=p.y+cardH/2,ex=c.x,ey=c.y-cardH/2,mid=(sy+ey)/2;
    links.appendChild(make("path",{d:`M ${sx} ${sy} C ${sx} ${mid}, ${ex} ${mid}, ${ex} ${ey}`,class:"tree-link","data-from":id,"data-to":childId}));
    renderLinks(childId);
  }
}
function renderNodes(id){
  const p=positions.get(id),state=report.nodes[id],g=make("g",{class:`node${id===rootId?" root":""}`,transform:`translate(${p.x-cardW/2},${p.y-cardH/2})`,"data-id":id,tabindex:"0",role:"button","aria-label":`${state.url||"state"}; ${actionFor(id)}`});
  g.appendChild(make("rect",{width:cardW,height:cardH}));
  const action=make("text",{x:12,y:23,class:"action"});action.textContent=actionFor(id).slice(0,31);g.appendChild(action);
  const route=make("text",{x:12,y:47,class:"route"});route.textContent=(state.url||"State").replace(/^https?:\/\/[^/]+/,"").slice(-25)||"Home";g.appendChild(route);
  const d=make("text",{x:12,y:69,class:"depth"});d.textContent=`depth ${depth.get(id)} · ${id.slice(0,10)}`;g.appendChild(d);
  g.addEventListener("click",()=>select(id));
  g.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select(id);}});
  nodeLayer.appendChild(g);
  for(const child of children.get(id)||[])renderNodes(child);
}
renderLinks(rootId);renderNodes(rootId);
document.getElementById("app-name").textContent=(location.pathname.split("/").pop()||"report").replace(/\.html$/i,"");
document.getElementById("summary").textContent=`${Object.keys(report.nodes).length} states · ${Array.from(children.values()).reduce((n,x)=>n+x.length,0)} transitions`;
function select(id){
  document.querySelectorAll(".node").forEach(n=>n.classList.toggle("selected",n.dataset.id===id));
  const state=report.nodes[id],parent=report.nodes[state.prev_state];
  document.getElementById("hint").hidden=true;document.getElementById("details").hidden=false;
  document.getElementById("detail-title").textContent=(state.url||"State").replace(/^https?:\/\/[^/]+/,"")||"Home";
  document.getElementById("state-id").textContent=id;
  document.getElementById("state-url").textContent=state.url||"—";
  document.getElementById("state-depth").textContent=String(depth.get(id));
  document.getElementById("state-action").textContent=parent?actionFor(id):"Initial state";
  document.getElementById("state-context").textContent=state.context||"No context recorded";
  document.getElementById("state-actions").textContent=(state.actions||[]).map(a=>a.testId||a.type||a.id).join(" · ")||"None";
  const chain=new Set();let cur=id;
  while(cur){chain.add(cur);cur=report.nodes[cur]?.prev_state;}
  document.querySelectorAll(".tree-link").forEach(path=>path.classList.toggle("is-path",chain.has(path.dataset.to)));
}
let scale=1,tx=0,ty=0;
function applyTransform(){viewport.setAttribute("transform",`translate(${tx} ${ty}) scale(${scale})`);}
function fit(){
  const box=document.getElementById("canvas").getBoundingClientRect();
  const visible=[...document.querySelectorAll(".node")].filter(n=>n.style.display!=="none").map(n=>positions.get(n.dataset.id));
  const minX=Math.min(...visible.map(p=>p.x-cardW/2)),maxX=Math.max(...visible.map(p=>p.x+cardW/2));
  const minY=Math.min(...visible.map(p=>p.y-cardH/2)),maxY=Math.max(...visible.map(p=>p.y+cardH/2));
  const graphW=maxX-minX,graphH=maxY-minY,baseScale=Math.min(box.width/width,box.height/height);
  const offsetX=(box.width-width*baseScale)/2,offsetY=(box.height-height*baseScale)/2;
  const screenScale=Math.min((box.width-50)/graphW,(box.height-50)/graphH);
  scale=screenScale/baseScale;
  tx=(box.width/2-offsetX)/baseScale-(minX+graphW/2)*scale;
  ty=(box.height/2-offsetY)/baseScale-(minY+graphH/2)*scale;
  applyTransform();
}
function svgPoint(clientX,clientY){const point=svg.createSVGPoint();point.x=clientX;point.y=clientY;return point.matrixTransform(svg.getScreenCTM().inverse());}
function zoom(factor,px,py){const next=Math.max(.08,Math.min(12,scale*factor)),r=next/scale;tx=px-(px-tx)*r;ty=py-(py-ty)*r;scale=next;applyTransform();}
document.getElementById("fit").addEventListener("click",fit);
document.getElementById("zoom-in").addEventListener("click",()=>{const r=svg.getBoundingClientRect(),p=svgPoint(r.left+r.width/2,r.top+r.height/2);zoom(1.2,p.x,p.y);});
document.getElementById("zoom-out").addEventListener("click",()=>{const r=svg.getBoundingClientRect(),p=svgPoint(r.left+r.width/2,r.top+r.height/2);zoom(.83,p.x,p.y);});
let focused=false;
document.getElementById("focus").addEventListener("click",()=>{
  const ids=focused?new Set(Object.keys(report.nodes)):new Set(descendants(document.querySelector(".node.selected")?.dataset.id||rootId));
  document.querySelectorAll(".node").forEach(n=>n.style.display=ids.has(n.dataset.id)?"":"none");
  document.querySelectorAll(".tree-link").forEach(p=>p.style.display=ids.has(p.dataset.from)&&ids.has(p.dataset.to)?"":"none");
  focused=!focused;
  document.getElementById("focus").textContent=focused?"Show full tree":"Focus branch";
  fit();
});
svg.addEventListener("wheel",e=>{e.preventDefault();const p=svgPoint(e.clientX,e.clientY);zoom(e.deltaY<0?1.12:.89,p.x,p.y);},{passive:false});
let drag=null;
svg.addEventListener("pointerdown",e=>{if(e.target.closest(".node"))return;const p=svgPoint(e.clientX,e.clientY);drag={x:p.x,y:p.y,tx,ty};svg.setPointerCapture(e.pointerId);});
svg.addEventListener("pointermove",e=>{if(!drag)return;const p=svgPoint(e.clientX,e.clientY);tx=drag.tx+p.x-drag.x;ty=drag.ty+p.y-drag.y;applyTransform();});
svg.addEventListener("pointerup",()=>drag=null);
document.getElementById("search").addEventListener("input",e=>{
  const q=e.target.value.trim().toLowerCase();
  document.querySelectorAll(".node").forEach(el=>{
    const id=el.dataset.id,state=report.nodes[id],text=[id,state.url,state.context,actionFor(id)].join(" ").toLowerCase();
    el.classList.toggle("search-hit",!!q&&text.includes(q));el.classList.toggle("search-muted",!!q&&!text.includes(q));
  });
});
window.addEventListener("resize",fit);
fit();
</script>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create an interactive HTML tree from an AutoE2E report."
    )
    parser.add_argument(
        "report",
        nargs="?",
        type=Path,
        default=Path("report/PETCLINIC.json"),
        help="Path to the AutoE2E JSON report",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output HTML path (defaults to the report path with .html extension)",
    )
    args = parser.parse_args()

    report_path = args.report
    output_path = args.output or report_path.with_suffix(".html")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    build_tree(report)
    embedded_json = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    html = HTML_TEMPLATE.replace("__REPORT_JSON__", embedded_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Interactive tree written to {output_path}")


if __name__ == "__main__":
    main()
