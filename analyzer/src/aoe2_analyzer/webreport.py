"""Self-contained HTML report for a parsed replay.

`build_html(summary)` returns a single HTML document (no external files, no
CDN — works offline, double-click to open, shareable) with:
  - head-to-head metric cards,
  - an age timeline (Dark/Feudal/Castle/Imperial bars per player),
  - interactive line charts (villagers / military / TC idle over time),
  - key events (resign / retreat / delete) on a timeline strip,
  - each human player's build order with TC-idle gaps highlighted.

Charts are drawn by a small inline vanilla-JS SVG renderer, so the only
moving part is the embedded JSON data block (`__DATA_JSON__`).
"""

from __future__ import annotations

import json

from .models import PlayerSummary, ReplaySummary
from .report import _counts_up_to, _cum_idle, _is_military

# Distinct, colour-blind-friendly-ish palette; players take these in order.
_PALETTE = ["#4f9dff", "#ff6b6b", "#ffd166", "#06d6a0", "#c792ea", "#f78c6c"]
_AGE_ORDER = ["Dark", "Feudal", "Castle", "Imperial"]


def _mmss(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


def _is_ai(p: PlayerSummary) -> bool:
    return p.is_ai


def _ages_estimated(p: PlayerSummary) -> bool:
    """True when this player's age times are inferred (AI), not real clicks."""
    return any(a.click_estimated for a in p.age_timings)


def _build_order_rows(p: PlayerSummary) -> list[dict]:
    """Flatten the build order to JSON rows, with TC-idle gaps interleaved."""
    rows: list[dict] = []
    idle = sorted(p.main_tc_idle_gaps, key=lambda g: g.start)
    gi = 0
    vill_no = 0

    def flush(until: float) -> None:
        nonlocal gi
        while gi < len(idle) and idle[gi].start <= until:
            g = idle[gi]
            rows.append({
                "t": _mmss(g.start), "kind": "idle",
                "label": f"TC idle {_mmss(g.seconds)} (≈ {g.seconds / 25.0:.1f} vills missed)",
            })
            gi += 1

    for e in p.build_order:
        flush(e.game_time)
        if e.kind == "age":
            rows.append({"t": _mmss(e.game_time), "kind": "age", "label": f"{e.name}"})
        elif e.kind == "building":
            rows.append({"t": _mmss(e.game_time), "kind": "building", "label": e.name})
        elif e.name == "Villager":
            if e.count == 1:
                vill_no += 1
                label = f"Villager #{vill_no}"
            else:
                label = f"Villager #{vill_no + 1}–#{vill_no + e.count}"
                vill_no += e.count
            rows.append({"t": _mmss(e.game_time), "kind": "vill", "label": label})
        else:
            label = e.name if e.count == 1 else f"{e.name} x{e.count}"
            rows.append({"t": _mmss(e.game_time), "kind": "mil", "label": label})
    flush(float("inf"))
    return rows


def _age_segments(p: PlayerSummary, duration: float) -> list[dict]:
    """Timeline segments: time spent IN each age, plus an 'advancing' sliver
    between the age-up CLICK and the (estimated) ARRIVAL — so the bar shows both
    when you decided to advance and when you were actually in the new age.
    """
    ages = []
    for name in _AGE_ORDER[1:]:  # Feudal, Castle, Imperial
        a = p.age(name)
        if a and a.click_time is not None:
            arrival = a.arrival_time if a.arrival_time is not None else a.click_time
            ages.append((name, a.click_time, arrival))

    segs: list[dict] = []
    cursor = 0.0
    current = "Dark"
    for name, click, arrival in ages:
        if click > cursor:
            segs.append({"age": current, "kind": "in", "start": cursor, "end": click})
        end_adv = min(arrival, duration)
        if end_adv > click:
            segs.append({"age": name, "kind": "adv", "start": click, "end": end_adv})
        cursor = max(cursor, end_adv)
        current = name
    if duration > cursor:
        segs.append({"age": current, "kind": "in", "start": cursor, "end": duration})
    return segs


def _player_data(p: PlayerSummary, color: str, duration: float, step: int) -> dict:
    marks = list(range(0, int(duration) + step, step))
    vills, mil, idle = [], [], []
    for t in marks:
        v, m, _ = _counts_up_to(p.build_order, t)
        vills.append([t, v])
        mil.append([t, m])
        idle.append([t, round(_cum_idle(p.main_tc_idle_gaps, t))])

    def click(age: str) -> float | None:
        a = p.age(age)
        return a.click_time if a and a.click_time is not None else None

    feudal = click("Feudal")
    # Guard: cutoff=None means "count everything", so only compute vills-by-Feudal
    # when the player actually reached Feudal (else AIs would show their grand total).
    vills_by_feudal = _counts_up_to(p.build_order, feudal)[0] if feudal is not None else None
    tv, tm, _ = _counts_up_to(p.build_order, None)
    est = "~" if _ages_estimated(p) else ""

    def age_str(age: str) -> str:
        t = click(age)
        return (est + _mmss(t)) if t is not None else "--:--"

    return {
        "name": p.name,
        "color": color,
        "isAI": _is_ai(p),
        "agesEstimated": _ages_estimated(p),
        "ages": {a: click(a) for a in _AGE_ORDER[1:]},
        "timeline": _age_segments(p, duration),
        "series": {"villagers": vills, "military": mil, "idle": None if _is_ai(p) else idle},
        "metrics": {
            "feudal": age_str("Feudal"),
            "castle": age_str("Castle"),
            "imperial": age_str("Imperial"),
            "f2c": _mmss(click("Castle") - feudal) if feudal and click("Castle") else "--:--",
            "villsByFeudal": vills_by_feudal if vills_by_feudal is not None else "—",
            "totalVills": tv,
            "totalMil": tm,
            "idleTotal": _mmss(p.total_idle_tc_seconds) if p.total_idle_tc_seconds is not None else "—",
        },
        "buildOrder": _build_order_rows(p),
    }


def build_html(
    summary: ReplaySummary,
    step: int = 20,
    games: list[dict] | None = None,
    selected: str | None = None,
    player_filter: list[str] | None = None,
) -> str:
    """Render the report. `games` (list of {file,label,players}) + `selected` +
    `player_filter` power the server's pickers; omit them for a standalone file."""
    duration = summary.game_duration_seconds or 0
    players = summary.players
    name_by_pid = {p.player_id: p.name for p in players}
    data = {
        "games": games or [],
        "selected": selected,
        "playerFilter": player_filter or [],
        "meta": {
            "matchup": " vs ".join(p.name for p in players) or "unknown",
            "version": summary.game_version or "unknown",
            "duration": _mmss(duration),
            "durationSec": duration,
            "map": summary.map_name or "unknown",
            "file": summary.source_file,
        },
        "players": [
            _player_data(p, _PALETTE[i % len(_PALETTE)], duration, step)
            for i, p in enumerate(players)
        ],
        "events": [
            {"t": e.game_time, "tStr": _mmss(e.game_time), "kind": e.kind,
             "player": name_by_pid.get(e.player_id, f"p{e.player_id}")}
            for e in sorted(summary.notable_events, key=lambda e: e.game_time)
        ],
    }
    return _TEMPLATE.replace("__DATA_JSON__", json.dumps(data))


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AoE2 — análisis de partida</title>
<style>
  :root{
    --bg:#0f1419; --panel:#1a2230; --panel2:#222d3d; --ink:#e6edf3;
    --muted:#8b98a9; --line:#2c3a4d; --accent:#4f9dff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:1100px;margin:0 auto;padding:24px 18px 80px}
  h1{font-size:24px;margin:0 0 2px} h2{font-size:18px;margin:34px 0 12px}
  .sub{color:var(--muted);font-size:13px;margin-bottom:6px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}
  .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}
  .card h3{margin:0 0 10px;font-size:15px;display:flex;align-items:center;gap:8px}
  .dot{width:11px;height:11px;border-radius:50%;display:inline-block;flex:0 0 auto}
  .tag{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:1px 6px}
  .metric{display:flex;justify-content:space-between;padding:3px 0;font-size:13px;border-top:1px dashed var(--line)}
  .metric:first-of-type{border-top:none}
  .metric .k{color:var(--muted)} .metric .v{font-variant-numeric:tabular-nums;font-weight:600}
  .best{color:#06d6a0} .worst{color:#ff6b6b}
  .tl-row{display:flex;align-items:center;gap:10px;margin:7px 0}
  .tl-name{width:130px;flex:0 0 auto;font-size:13px;display:flex;align-items:center;gap:7px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .tl-bar{flex:1;height:26px;border-radius:6px;overflow:hidden;display:flex;background:#0b0f15;border:1px solid var(--line)}
  .tl-seg{display:flex;align-items:center;justify-content:center;font-size:11px;color:#0b0f15;font-weight:700;white-space:nowrap;overflow:hidden}
  .tl-seg.adv{color:#e6edf3;font-weight:600;font-style:italic}
  .legend{display:flex;flex-wrap:wrap;gap:14px;margin:6px 0 10px}
  .legend span{cursor:pointer;font-size:13px;display:flex;align-items:center;gap:6px;user-select:none;opacity:1}
  .legend span.off{opacity:.32;text-decoration:line-through}
  .chart{width:100%;height:260px;touch-action:none}
  .charts{display:grid;grid-template-columns:1fr;gap:18px}
  .ev-strip{position:relative;height:54px;margin-top:8px;border:1px solid var(--line);border-radius:8px;background:#0b0f15}
  .ev{position:absolute;top:6px;width:2px;height:30px;cursor:default}
  .ev-lab{position:absolute;bottom:3px;font-size:10px;color:var(--muted);transform:translateX(-50%)}
  details{margin:8px 0;border:1px solid var(--line);border-radius:10px;background:var(--panel);overflow:hidden}
  summary{cursor:pointer;padding:11px 14px;font-weight:600;display:flex;align-items:center;gap:8px}
  .bo{max-height:360px;overflow:auto;padding:4px 14px 14px;font:13px/1.45 ui-monospace,Menlo,Consolas,monospace}
  .bo div{display:flex;gap:10px;padding:1px 0}
  .bo .t{color:var(--muted);width:46px;flex:0 0 auto;text-align:right}
  .bo .idle{color:#ffb454;background:#2a210f;border-radius:4px;padding:0 4px;margin:1px 0}
  .bo .age{color:#06d6a0;font-weight:700;border-top:1px solid var(--line);margin-top:4px;padding-top:4px}
  .bo .mil{color:#ff8f8f} .bo .vill{color:#cfe3ff} .bo .building{color:#9fb3c8}
  .tip{position:fixed;pointer-events:none;background:#0b0f15;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;font-size:12px;opacity:0;transition:opacity .08s;z-index:9;
    box-shadow:0 6px 20px rgba(0,0,0,.4);font-variant-numeric:tabular-nums}
  .foot{color:var(--muted);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:12px}
  a{color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
  <div id="picker" style="margin-bottom:14px"></div>
  <h1 id="title"></h1>
  <div class="sub" id="meta"></div>

  <h2>Comparación</h2>
  <div class="cards" id="cards"></div>

  <h2>Línea de edades</h2>
  <div class="sub">Color sólido = <b>en la era</b> · rayado <i>▸ subiendo</i> = <b>avanzando</b> (del click a la llegada ~estimada)</div>
  <div class="panel" id="timeline"></div>

  <h2>Progresión</h2>
  <div class="legend" id="legend"></div>
  <div class="charts">
    <div class="panel"><div class="sub">👤 Villagers (acumulado encolado)</div><svg class="chart" id="c_villagers"></svg></div>
    <div class="panel"><div class="sub">⚔️ Militares (acumulado encolado)</div><svg class="chart" id="c_military"></svg></div>
    <div class="panel"><div class="sub">⏳ TC idle (acumulado — más bajo es mejor)</div><svg class="chart" id="c_idle"></svg></div>
  </div>

  <h2>Eventos clave</h2>
  <div class="panel">
    <div class="sub">🏳️ resign &nbsp; 🔙 retirada &nbsp; 🗑️ delete — pasa el cursor por encima</div>
    <div class="ev-strip" id="events"></div>
  </div>

  <h2>Build orders</h2>
  <div id="builds"></div>

  <div class="foot">
    Datos reales del command stream. Conteos = unidades <b>encoladas</b> (no vivas); excluyen los 3 villagers + scout iniciales.
    TC idle se modela solo para jugadores humanos. Las edades de la IA (<span class="tag">~est</span>) son
    <b>estimadas</b> por el primer edificio de cada era (la IA no registra su subida de edad). Generado por <code>aoe report</code>.
  </div>
</div>

<div class="tip" id="tip"></div>

<script>
const DATA = __DATA_JSON__;
const $ = (id)=>document.getElementById(id);
const tip = $("tip");
function showTip(html,x,y){tip.innerHTML=html;tip.style.opacity=1;
  tip.style.left=Math.min(x+14,innerWidth-tip.offsetWidth-8)+"px";
  tip.style.top=(y+14)+"px";}
function hideTip(){tip.style.opacity=0;}

// ---- pickers (only on the server, when games are available) ----
if(DATA.games && DATA.games.length){
  const selCss="background:#1a2230;color:#e6edf3;border:1px solid #2c3a4d;"+
    "border-radius:8px;padding:8px 10px;font-size:14px;max-width:100%";
  const labCss="color:#8b98a9;font-size:13px;margin:0 8px 0 0";
  const curPlayer=new URLSearchParams(location.search).get("player")||"";

  // player filter (regular players only — AI personalities are excluded server-side)
  let playerSel=null;
  if((DATA.playerFilter||[]).length){
    playerSel=document.createElement("select");
    playerSel.style.cssText=selCss+";min-width:160px";
    const optAll=document.createElement("option");
    optAll.value="";optAll.textContent="Todos los jugadores";playerSel.appendChild(optAll);
    DATA.playerFilter.forEach(n=>{const o=document.createElement("option");
      o.value=n;o.textContent=n;if(n===curPlayer)o.selected=true;playerSel.appendChild(o);});
    const l=document.createElement("span");l.textContent="Jugador: ";l.style.cssText=labCss;
    $("picker").appendChild(l);$("picker").appendChild(playerSel);
  }

  // game picker, filtered by the chosen player
  const gameSel=document.createElement("select");
  gameSel.style.cssText=selCss+";min-width:340px;margin-left:14px";
  function fillGames(player){
    gameSel.innerHTML="";
    const list=DATA.games.filter(g=>!player||(g.players||[]).includes(player));
    list.forEach(g=>{const o=document.createElement("option");
      o.value=g.file;o.textContent=g.label;if(g.file===DATA.selected)o.selected=true;gameSel.appendChild(o);});
    const lg=document.createElement("span");lg.id="gcount";
  }
  fillGames(curPlayer);
  gameSel.onchange=()=>{const p=playerSel?playerSel.value:"";
    location.search="?game="+encodeURIComponent(gameSel.value)+(p?"&player="+encodeURIComponent(p):"");};
  if(playerSel) playerSel.onchange=()=>{fillGames(playerSel.value);
    const c=$("gcount"); if(c) c.textContent=` ${gameSel.options.length} partidas`;};

  const lg=document.createElement("span");lg.textContent="Partida: ";lg.style.cssText=labCss+";margin-left:14px";
  $("picker").appendChild(lg);$("picker").appendChild(gameSel);
  const cnt=document.createElement("span");cnt.id="gcount";cnt.style.cssText=labCss+";margin-left:8px";
  cnt.textContent=` ${gameSel.options.length} partidas`;$("picker").appendChild(cnt);
}

// ---- header ----
$("title").textContent = "🏹 " + DATA.meta.matchup;
$("meta").textContent = `${DATA.meta.version} · ${DATA.meta.duration} · mapa: ${DATA.meta.map}`;

// ---- cards (winner highlight across ALL players, per metric) ----
function num(v){ // mm:ss -> seconds, plain number -> itself, else NaN
  if(typeof v==="number")return v;
  if(typeof v==="string"&&/^\d+:\d\d$/.test(v)){const a=v.split(":");return +a[0]*60+ +a[1];}
  return NaN;
}
// metric key, label, and whether lower is better
const METRICS=[
  ["feudal","Feudal",true],["castle","Castle",true],["imperial","Imperial",true],
  ["f2c","Feudal→Castle",true],["villsByFeudal","Vills @Feudal",false],
  ["totalVills","Vills totales",false],["totalMil","Militares",false],["idleTotal","TC idle",true],
];
// winning value per metric (numeric)
const winners={};
METRICS.forEach(([k,,low])=>{
  let best=null;
  DATA.players.forEach(p=>{const n=num(p.metrics[k]);if(isNaN(n))return;
    if(best===null||(low?n<best:n>best))best=n;});
  winners[k]=best;
});
const cards = $("cards");
DATA.players.forEach(p=>{
  const m=p.metrics;
  const card=document.createElement("div"); card.className="card";
  card.innerHTML = `<h3><span class="dot" style="background:${p.color}"></span>${p.name}`+
    (p.isAI?` <span class="tag">IA</span>`:``)+`</h3>`+
    METRICS.map(([k,lab])=>{
      const n=num(m[k]);
      const win=!isNaN(n)&&winners[k]!==null&&n===winners[k];
      return `<div class="metric"><span class="k">${lab}</span>`+
             `<span class="v ${win?"best":""}">${m[k]}${win?" ✓":""}</span></div>`;
    }).join("");
  cards.appendChild(card);
});

// ---- age timeline ----
const DUR = DATA.meta.durationSec || 1;
const ageColors={Dark:"#5b6b7d",Feudal:"#e0a458",Castle:"#7d6bd6",Imperial:"#cf5b5b"};
const tl=$("timeline");
DATA.players.forEach(p=>{
  const segs=(p.timeline||[]).map(s=>{
    const w=Math.max(0,(s.end-s.start))/DUR*100; if(w<=0) return "";
    const col=ageColors[s.age]||"#5b6b7d";
    if(s.kind==="adv"){
      // "avanzando": diagonal stripes of the target age colour
      const bg=`repeating-linear-gradient(45deg,${col} 0 5px,#0b0f15 5px 10px)`;
      return `<div class="tl-seg adv" style="width:${w}%;background:${bg}" `+
             `title="Avanzando a ${s.age}: ${fmt(s.start)}→${fmt(s.end)} (subiendo)">${w>11?"▸ subiendo":""}</div>`;
    }
    return `<div class="tl-seg" style="width:${w}%;background:${col};color:#0b0f15" `+
           `title="${s.age}: ${fmt(s.start)}→${fmt(s.end)}">${w>9?s.age:""}</div>`;
  });
  const row=document.createElement("div"); row.className="tl-row";
  const estTag = p.agesEstimated ? ` <span class="tag">~est</span>` : "";
  row.innerHTML=`<div class="tl-name"><span class="dot" style="background:${p.color}"></span>${p.name}${estTag}</div>`+
    `<div class="tl-bar">${segs.join("")}</div>`;
  tl.appendChild(row);
});
function fmt(s){s=Math.round(s);return String(Math.floor(s/60)).padStart(2,"0")+":"+String(s%60).padStart(2,"0");}

// ---- charts ----
const hidden=new Set();
const SERIES=["villagers","military","idle"];
function drawChart(svgId, key){
  const svg=$(svgId); const W=svg.clientWidth||800, H=svg.clientHeight||260;
  const padL=44,padR=12,padT=12,padB=24;
  let maxY=1, maxX=DUR;
  DATA.players.forEach(p=>{const s=p.series[key]; if(!s||hidden.has(p.name))return;
    s.forEach(pt=>{if(pt[1]>maxY)maxY=pt[1];});});
  maxY=Math.ceil(maxY*1.1/5)*5||5;
  const X=t=>padL+(t/maxX)*(W-padL-padR);
  const Y=v=>H-padB-(v/maxY)*(H-padT-padB);
  let svgEl=`<rect x="0" y="0" width="${W}" height="${H}" fill="transparent"/>`;
  // gridlines + y labels
  for(let g=0;g<=4;g++){const v=maxY*g/4;const y=Y(v);
    svgEl+=`<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="#2c3a4d" stroke-width="1"/>`;
    svgEl+=`<text x="${padL-6}" y="${y+4}" fill="#8b98a9" font-size="11" text-anchor="end">${Math.round(v)}</text>`;}
  // x labels every 5 min
  for(let t=0;t<=maxX;t+=300){svgEl+=`<text x="${X(t)}" y="${H-6}" fill="#8b98a9" font-size="11" text-anchor="middle">${fmt(t)}</text>`;}
  // age click markers (vertical dashed) for humans
  DATA.players.forEach(p=>{if(hidden.has(p.name))return;
    ["Feudal","Castle","Imperial"].forEach(a=>{const t=p.ages[a];if(t==null)return;
      svgEl+=`<line x1="${X(t)}" y1="${padT}" x2="${X(t)}" y2="${H-padB}" stroke="${p.color}" stroke-opacity=".18" stroke-dasharray="3 3"/>`;});});
  // lines
  DATA.players.forEach(p=>{const s=p.series[key]; if(!s||hidden.has(p.name))return;
    const d=s.map((pt,i)=>(i?"L":"M")+X(pt[0]).toFixed(1)+" "+Y(pt[1]).toFixed(1)).join(" ");
    svgEl+=`<path d="${d}" fill="none" stroke="${p.color}" stroke-width="2.2" stroke-linejoin="round"/>`;});
  svgEl+=`<line class="cursor" x1="0" y1="${padT}" x2="0" y2="${H-padB}" stroke="#e6edf3" stroke-opacity="0" stroke-width="1"/>`;
  svg.innerHTML=svgEl;
  // hover
  svg.onpointermove=(ev)=>{const r=svg.getBoundingClientRect();const mx=ev.clientX-r.left;
    if(mx<padL||mx>W-padR){hideTip();return;}
    const t=Math.max(0,Math.min(maxX,(mx-padL)/(W-padL-padR)*maxX));
    const cur=svg.querySelector(".cursor"); if(cur){cur.setAttribute("x1",mx);cur.setAttribute("x2",mx);cur.setAttribute("stroke-opacity",".4");}
    let rows=`<b>${fmt(t)}</b>`;
    DATA.players.forEach(p=>{const s=p.series[key];if(!s||hidden.has(p.name))return;
      let best=s[0];for(const pt of s){if(pt[0]<=t)best=pt;else break;}
      rows+=`<br><span style="color:${p.color}">●</span> ${p.name}: <b>${key==="idle"?fmt(best[1]):best[1]}</b>`;});
    showTip(rows,ev.clientX,ev.clientY);};
  svg.onpointerleave=()=>{hideTip();const cur=svg.querySelector(".cursor");if(cur)cur.setAttribute("stroke-opacity","0");};
}
function drawAll(){SERIES.forEach(k=>drawChart("c_"+k,k));}

// legend (toggle players)
const lg=$("legend");
DATA.players.forEach(p=>{const s=document.createElement("span");
  s.innerHTML=`<span class="dot" style="background:${p.color}"></span>${p.name}`+(p.isAI?" (IA)":"");
  s.onclick=()=>{if(hidden.has(p.name))hidden.delete(p.name);else hidden.add(p.name);
    s.classList.toggle("off");drawAll();};
  lg.appendChild(s);});

// ---- events strip ----
const ic={RESIGN:"🏳️",DE_RETREAT:"🔙",DELETE:"🗑️"};
const es=$("events");
DATA.events.forEach(e=>{const x=(e.t/DUR)*100;
  const m=document.createElement("div");m.className="ev";m.style.left=x+"%";
  const col=e.kind==="RESIGN"?"#ff6b6b":e.kind==="DE_RETREAT"?"#ffd166":"#8b98a9";
  m.style.background=col;
  m.onpointerenter=(ev)=>showTip(`<b>${e.tStr}</b><br>${ic[e.kind]||""} ${e.kind} — ${e.player}`,ev.clientX,ev.clientY);
  m.onpointerleave=hideTip;
  es.appendChild(m);
  const lab=document.createElement("div");lab.className="ev-lab";lab.style.left=x+"%";
  lab.textContent=ic[e.kind]||"";es.appendChild(lab);});

// ---- build orders ----
const bd=$("builds");
DATA.players.filter(p=>p.buildOrder.length).forEach(p=>{
  const d=document.createElement("details");
  const idleN=p.buildOrder.filter(r=>r.kind==="idle").length;
  d.innerHTML=`<summary><span class="dot" style="background:${p.color}"></span>${p.name}`+
    (p.isAI?` <span class="tag">IA</span>`:` <span class="tag">${idleN} huecos TC</span>`)+
    `</summary>`+
    `<div class="bo">`+p.buildOrder.map(r=>
      r.kind==="idle"
      ? `<div class="idle"><span class="t">${r.t}</span>⏳ ${r.label}</div>`
      : `<div class="${r.kind}"><span class="t">${r.t}</span>${r.kind==="age"?"▸ ":""}${r.label}</div>`
    ).join("")+`</div>`;
  bd.appendChild(d);
});

drawAll();
addEventListener("resize",drawAll);
</script>
</body>
</html>
"""
