"""Build a self-contained interactive 3D thermal Digital Twin HTML from an STL.

It bakes the colleague's realistic STL geometry together with the calibrated
physics from our backend (em_solver loss values + I^2 scaling + a lumped thermal
network) into ONE standalone digital_twin.html file (geometry + data embedded as
base64, so it runs by double-clicking, no server needed).

Run:
    python tools/build_twin_html.py [path/to/model.stl]

Region mapping (indicative, by radius/height of each triangle centroid):
    0 plate (top disc)   1 inner coil   2 outer coil   3 iron core   4 structure/base
"""
from __future__ import annotations
import sys, os, struct, base64, json, math, copy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)
from config import load_config            # noqa: E402
from em_solver import compute_losses      # noqa: E402


# --------------------------------------------------------------------------
# STL parsing (binary) -> (nTri, 3, 3) vertex array in millimetres
# --------------------------------------------------------------------------
def parse_stl(path):
    raw = open(path, "rb").read()
    n = struct.unpack("<I", raw[80:84])[0]
    off, tris = 84, []
    for _ in range(n):
        d = struct.unpack("<12fH", raw[off:off + 50]); off += 50
        tris.append(d[3:12])
    return np.array(tris, dtype=np.float32).reshape(-1, 3, 3) * 1000.0  # m -> mm


# --------------------------------------------------------------------------
# Classify each triangle into a physics region by its centroid (r, z) [mm]
# Thresholds are easy to tweak here.
# --------------------------------------------------------------------------
def classify(V):
    C = V.mean(axis=1)
    r = np.hypot(C[:, 0], C[:, 1])
    z = C[:, 2]
    z_top = z.max() - 0.18 * (z.max() - z.min())   # top slab = plate
    region = np.full(len(C), 4, dtype=np.uint8)    # default: structure
    region[(z > z_top) & (r <= 90)] = 0            # plate
    body = z <= z_top
    region[body & (r <= 26)] = 3                   # iron core (central)
    region[body & (r > 26) & (r <= 45)] = 1        # inner coil
    region[body & (r > 45) & (r <= 62)] = 2        # outer coil
    return region


# --------------------------------------------------------------------------
# Physics parameters from our backend
# --------------------------------------------------------------------------
def physics_params(cfg):
    L = compute_losses(cfg)
    mm = 1e-3
    co = cfg.coils
    A_wire = math.pi * (co["wire_diameter_mm"] * mm / 2) ** 2

    def coil_R(c):
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        return c["turns"] * (2 * math.pi * r_mean) / (co["sigma_Cu_S_per_m"] * A_wire)

    P_inner = 0.5 * cfg.I ** 2 * coil_R(co["inner"])
    P_outer = 0.5 * cfg.I ** 2 * coil_R(co["outer"])

    # thermal capacities C = rho * cp * V  [J/K]
    p = cfg.plate
    V_plate = math.pi * (p["radius_mm"] * mm) ** 2 * (p["thickness_mm"] * mm)
    C_plate = p["rho_kg_per_m3"] * p["cp_J_per_kgK"] * V_plate

    def coil_C(c):  # copper: rho=8960, cp=385; volume = N * turn_len * A_wire
        r_mean = (c["r_inner_mm"] + c["r_outer_mm"]) / 2 * mm
        Vc = c["turns"] * (2 * math.pi * r_mean) * A_wire
        return 8960.0 * 385.0 * Vc

    # --- payload (object sitting on the plate): one extra EM solve with the
    #     payload enabled at a reference radius, so the browser can scale it.
    #     Thin-disc eddy loss ~ R^4, thermal capacity & convection area ~ R^2.
    pl = cfg.raw.get("payload_model", {})
    R_ref_pl = float(pl.get("radius_mm", 40.0))
    t_pl     = float(pl.get("thickness_mm", 5.0))
    rho_pl   = float(pl.get("rho_kg_per_m3", 7850.0))
    cp_pl    = float(pl.get("cp_J_per_kgK", 490.0))
    cfg_pl = copy.deepcopy(cfg)
    cfg_pl.raw["payload_model"]["enabled"]   = True
    cfg_pl.raw["payload_model"]["radius_mm"] = R_ref_pl
    P_payload_ref = compute_losses(cfg_pl)["P_payload_W"]
    V_pl_ref = math.pi * (R_ref_pl * mm) ** 2 * (t_pl * mm)
    C_pl_ref = rho_pl * cp_pl * V_pl_ref
    hA_pl_ref = 10.0 * (math.pi * (R_ref_pl * mm) ** 2 + 2 * math.pi * (R_ref_pl * mm) * (t_pl * mm))

    # PROVISIONAL convection hA [W/K] chosen for plausible steady temps.
    # These are the CALIBRATION knobs to fit against real sensors (Phase 3).
    return {
        "I_ref": cfg.I, "T_amb": cfg.bc["T_ambient_degC"],
        "nodes": {
            "plate": {"P_ref": L["P_plate_W"], "C": C_plate, "hA": 0.15, "region": 0},
            "inner": {"P_ref": P_inner,        "C": coil_C(co["inner"]), "hA": 0.48, "region": 1},
            "outer": {"P_ref": P_outer,        "C": coil_C(co["outer"]), "hA": 0.44, "region": 2},
            "iron":  {"P_ref": L["P_iron_W"],  "C": 0.5 * C_plate,       "hA": 0.06, "region": 3},
        },
        # payload handled separately in JS (radius is a live slider)
        "payload": {
            "P_ref": P_payload_ref, "C_ref": C_pl_ref, "hA_ref": hA_pl_ref,
            "R_ref_mm": R_ref_pl, "R_min_mm": 10.0, "R_max_mm": 90.0, "t_mm": t_pl,
        },
        "P_total_ref": L["P_total_W"],
    }


def build(stl_path, out_path):
    cfg = load_config()
    V = parse_stl(stl_path)
    region = classify(V)
    params = physics_params(cfg)

    # report segmentation so we can sanity check
    names = {0: "plate", 1: "inner", 2: "outer", 3: "iron", 4: "structure"}
    print("Region triangle counts:")
    for k in range(5):
        print(f"  {names[k]:10s}: {(region == k).sum()}")
    print(f"P_ref (I={cfg.I}A): plate={params['nodes']['plate']['P_ref']*1e3:.0f}mW "
          f"inner={params['nodes']['inner']['P_ref']:.1f}W "
          f"outer={params['nodes']['outer']['P_ref']:.1f}W "
          f"total={params['P_total_ref']:.1f}W")

    pos = V.reshape(-1).astype("<f4").tobytes()          # 3*nTri vertices xyz
    pos_b64 = base64.b64encode(pos).decode()
    reg_b64 = base64.b64encode(region.tobytes()).decode()

    html = (TEMPLATE
            .replace("__POS_B64__", pos_b64)
            .replace("__REG_B64__", reg_b64)
            .replace("__PARAMS__", json.dumps(params)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nWrote {out_path}  ({len(html)/1024:.0f} KB)  -> double-click to run.")


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Digital Twin - Thermal (real STL + calibrated physics)</title>
<style>
 body{margin:0;overflow:hidden;background:#1a1a2e;color:#fff;font-family:'Segoe UI',Tahoma,sans-serif}
 #ui{position:absolute;top:15px;left:15px;display:flex;gap:18px;pointer-events:none;z-index:10}
 .panel{background:rgba(15,15,30,.85);padding:18px;border-radius:12px;border:1px solid #333;
   pointer-events:auto;backdrop-filter:blur(5px);box-shadow:0 4px 6px rgba(0,0,0,.3);width:290px}
 h2{margin:0 0 12px;font-size:1.1rem;border-bottom:1px solid #444;padding-bottom:5px;color:#4facfe}
 .cg{margin-bottom:14px}
 .cg label{display:flex;justify-content:space-between;margin-bottom:5px;font-size:.9rem}
 input[type=range]{width:100%;cursor:pointer}
 .row{display:flex;justify-content:space-between;margin-bottom:8px;font-size:.92rem;align-items:center}
 .box{width:14px;height:14px;border-radius:3px;margin-right:9px;display:inline-block}
 .val{font-family:monospace;font-size:1.05rem;font-weight:bold}
 #scale{margin-top:12px;width:100%;height:14px;border-radius:4px;
   background:linear-gradient(to right,#0000ff,#00ffff,#00ff00,#ffff00,#ff0000)}
 .sl{display:flex;justify-content:space-between;font-size:.78rem;margin-top:4px;color:#aaa}
 .note{font-size:.74rem;color:#888;line-height:1.4;margin-top:6px}
 button{pointer-events:auto;background:#26314f;color:#fff;border:1px solid #4facfe;border-radius:6px;
   padding:6px 10px;cursor:pointer;font-size:.85rem}
</style></head><body>
<div id="ui">
 <div class="panel"><h2>Physics Controls</h2>
  <div class="cg"><label><span>Current (I)</span><span id="vI">20.0 A</span></label>
    <input type="range" id="sI" min="0" max="20" step="0.5" value="20"></div>
  <div class="cg"><label><span>Payload radius</span><span id="vR">40 mm</span></label>
    <input type="range" id="sR" min="10" max="90" step="1" value="40"></div>
  <div class="cg"><label><span>Time speed</span><span id="vS">120x</span></label>
    <input type="range" id="sS" min="1" max="500" step="1" value="120"></div>
  <button id="reset">Reset temperatures</button>
  <p class="note">DEMO (not yet calibrated). Geometry: real STL. Losses from FEM
   (em_solver), scaled q&prop;I&sup2;; payload eddy&prop;R&#8308;. Time speed sets how
   fast the thermal field evolves around model, payload &amp; environment.</p>
 </div>
 <div class="panel"><h2>Thermal Telemetry</h2>
  <div class="row"><span>Sim time</span><span class="val" id="vT">0 s</span></div>
  <div class="row"><span>Total heat</span><span class="val" id="vP">0 W</span></div>
  <hr style="border:0;border-top:1px solid #333;margin:12px 0">
  <div class="row"><div><span class="box" id="bP"></span>Alu plate</div><span class="val" id="tP">25.0 &deg;C</span></div>
  <div class="row"><div><span class="box" id="bPl"></span>Payload disc</div><span class="val" id="tPl">25.0 &deg;C</span></div>
  <div class="row"><div><span class="box" id="bI"></span>Inner coil (1000)</div><span class="val" id="tI">25.0 &deg;C</span></div>
  <div class="row"><div><span class="box" id="bO"></span>Outer coil (500)</div><span class="val" id="tO">25.0 &deg;C</span></div>
  <div class="row"><div><span class="box" id="bFe"></span>Iron core</div><span class="val" id="tFe">25.0 &deg;C</span></div>
  <div class="row"><div><span class="box" id="bAir"></span>Ambient air</div><span class="val" id="tAir">25.0 &deg;C</span></div>
  <div id="scale"></div><div class="sl"><span>25&deg;C</span><span>150&deg;C+</span></div>
 </div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const PARAMS = __PARAMS__;
function b64ToBuf(b64){const s=atob(b64);const a=new Uint8Array(s.length);
  for(let i=0;i<s.length;i++)a[i]=s.charCodeAt(i);return a.buffer;}
const positions = new Float32Array(b64ToBuf("__POS_B64__"));
// Rotate CAD Z-up → Three.js Y-up: (x,y,z)→(x,z,−y)
for(let i=0;i<positions.length;i+=3){const y=positions[i+1],z=positions[i+2];positions[i+1]=z;positions[i+2]=-y;}
const regions   = new Uint8Array (b64ToBuf("__REG_B64__"));   // one id per triangle

// ---------- lumped thermal model ----------
// Bodies (plate/coils/iron/payload) convect into a shared AMBIENT-AIR node
// (the environment), which in turn loses heat to a fixed far ambient. So you can
// watch heat flow from the model + payload OUT into the surrounding environment.
const Eng = {
 t:0, Tfar:PARAMS.T_amb, Tair:PARAMS.T_amb,
 C_air:3000.0, hA_far:40.0,                                 // illustrative environment node
 T:{plate:PARAMS.T_amb,inner:PARAMS.T_amb,outer:PARAMS.T_amb,iron:PARAMS.T_amb,payload:PARAMS.T_amb},
 step:function(I,R,dt){
   const s2=(I/PARAMS.I_ref)**2;
   let Qconv=0;
   // fixed-region bodies (FEM-anchored, q ~ I^2)
   for(const k in PARAMS.nodes){const nd=PARAMS.nodes[k];
     const q=nd.P_ref*s2;
     const out=nd.hA*(this.T[k]-this.Tair);                 // convect into local air
     this.T[k]+=((q-out)/nd.C)*dt; Qconv+=out;}
   // payload disc: eddy loss ~ R^4, capacity & convection area ~ R^2
   const pl=PARAMS.payload, rr=R/pl.R_ref_mm;
   const qPl=pl.P_ref*Math.pow(rr,4)*s2;
   const CPl=Math.max(pl.C_ref*rr*rr,1e-3);
   const hAPl=pl.hA_ref*rr*rr;
   const outPl=hAPl*(this.T.payload-this.Tair);
   this.T.payload+=((qPl-outPl)/CPl)*dt; Qconv+=outPl;
   // environment air: gains all convection, loses to far ambient
   this.Tair+=((Qconv-this.hA_far*(this.Tair-this.Tfar))/this.C_air)*dt;
   this.t+=dt;
 },
 power:function(I,R){let p=0;const s2=(I/PARAMS.I_ref)**2;
   for(const k in PARAMS.nodes)p+=PARAMS.nodes[k].P_ref*s2;
   const rr=R/PARAMS.payload.R_ref_mm; p+=PARAMS.payload.P_ref*Math.pow(rr,4)*s2;
   return p;}
};
// temperature -> color (25..150 C : blue->red via HSL)
function tcol(T){let t=(T-25)/125;t=Math.max(0,Math.min(1,t));
  const c=new THREE.Color();c.setHSL((1-t)*240/360,1,0.5);return c;}
const STRUCT=new THREE.Color(0x6a6a78);                      // neutral grey for housing
const regionTempKey={0:'plate',1:'inner',2:'outer',3:'iron'};

// ---------- scene ----------
const scene=new THREE.Scene();scene.fog=new THREE.FogExp2(0x1a1a2e,0.0016);
const camera=new THREE.PerspectiveCamera(45,innerWidth/innerHeight,0.1,4000);
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
renderer.setSize(innerWidth,innerHeight);document.body.appendChild(renderer.domElement);
renderer.domElement.style.cssText='position:absolute;top:0;left:0;z-index:0;';
const controls=new THREE.OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.dampingFactor=0.08;
// Sliders/buttons live in .panel (pointer-events:auto). #ui itself is
// pointer-events:none, so enter/leave never fired on it — gate on .panel instead,
// and swallow pointer/wheel events so a drag on a slider never reaches OrbitControls.
document.querySelectorAll('.panel').forEach(p=>{
  p.addEventListener('pointerenter',()=>{controls.enabled=false;});
  p.addEventListener('pointerleave',()=>{controls.enabled=true;});
  ['pointerdown','mousedown','wheel','touchstart'].forEach(ev=>
    p.addEventListener(ev,e=>e.stopPropagation(),{passive:false}));
});
// ---------- split the STL into a LEVITATING plate (region 0) and the fixed BASE
//            (coils/iron/structure). This lets the plate float above the coils with
//            a visible air gap — the whole point of an electrodynamic levitator. ----------
function buildSub(keep){
  const P=[],G=[];
  for(let tri=0;tri<regions.length;tri++){
    if(!keep(regions[tri])) continue;
    for(let v=0;v<3;v++){const i=(tri*3+v)*3;P.push(positions[i],positions[i+1],positions[i+2]);}
    G.push(regions[tri]);
  }
  return {pos:new Float32Array(P),reg:new Uint8Array(G)};
}
function makeMesh(sub){
  const g=new THREE.BufferGeometry();
  g.setAttribute('position',new THREE.BufferAttribute(sub.pos,3));
  g.computeVertexNormals();
  const col=new Float32Array(sub.pos.length);
  g.setAttribute('color',new THREE.BufferAttribute(col,3));
  const m=new THREE.Mesh(g,new THREE.MeshStandardMaterial({vertexColors:true,roughness:0.45,metalness:0.55}));
  return {mesh:m,geo:g,reg:sub.reg,col:col};
}
const baseM=makeMesh(buildSub(r=>r!==0));     // coils + iron + structure (fixed)
const plateM=makeMesh(buildSub(r=>r===0));    // aluminium plate (levitates)
// bounding box / centre from the full model
const bb=new THREE.Box3();
{const t=new THREE.BufferGeometry();t.setAttribute('position',new THREE.BufferAttribute(positions,3));
 t.computeBoundingBox();bb.copy(t.boundingBox);}
const ctr=new THREE.Vector3();bb.getCenter(ctr);
const size=bb.getSize(new THREE.Vector3()).length();
const modelH=bb.max.y-bb.min.y;
const LIFT=Math.max(modelH*0.40,size*0.07);    // exaggerated levitation gap (real ~11mm)
baseM.mesh.position.set(-ctr.x,-ctr.y,-ctr.z);
plateM.mesh.position.set(-ctr.x,-ctr.y+LIFT,-ctr.z);
scene.add(baseM.mesh,plateM.mesh);
// ---- field-line hints: thin segments bridging the coil rim and the floating plate
const rRim=Math.min(size*0.18,90), gapTop=(bb.max.y-ctr.y), gapBot=(bb.max.y-ctr.y)-modelH*0.12;
const flPts=[];for(let a=0;a<12;a++){const th=a/12*Math.PI*2,x=Math.cos(th)*rRim,z=Math.sin(th)*rRim;
  flPts.push(x,gapBot,z, x,gapTop+LIFT*0.9,z);}
const flGeo=new THREE.BufferGeometry();flGeo.setAttribute('position',new THREE.Float32BufferAttribute(flPts,3));
scene.add(new THREE.LineSegments(flGeo,new THREE.LineBasicMaterial({color:0x4facfe,transparent:true,opacity:0.28})));
camera.position.set(size*0.78,size*0.40,size*0.78);
controls.target.set(0,LIFT*0.55,0);controls.update();
scene.add(new THREE.AmbientLight(0xffffff,0.55));
const dl=new THREE.DirectionalLight(0xffffff,0.9);dl.position.set(1,1.4,0.8);scene.add(dl);
const gh=new THREE.GridHelper(size*2,40,0x444444,0x222222);
gh.position.y=(bb.min.y-ctr.y);scene.add(gh);
// ---------- payload disc — rests ON the levitating plate (procedural, not in STL) ----------
const PL=PARAMS.payload;
const payGeo=new THREE.CylinderGeometry(PL.R_ref_mm,PL.R_ref_mm,PL.t_mm,64);
// CylinderGeometry axis is Y by default — matches our Y-up scene, no rotation needed
const payMat=new THREE.MeshStandardMaterial({roughness:0.3,metalness:0.7,color:0x8899aa});
const payload=new THREE.Mesh(payGeo,payMat);
const plateTopY=(bb.max.y-ctr.y)+LIFT;         // top surface of the lifted plate
payload.position.set(0,plateTopY+PL.t_mm*0.5,0);
scene.add(payload);
const FOG_BASE=new THREE.Color(0x1a1a2e), FOG_HOT=new THREE.Color(0x3a2030);
// update vertex colors from node temps (both base + plate meshes)
function paintMesh(M){
  for(let tri=0;tri<M.reg.length;tri++){
    const reg=M.reg[tri];
    const col=(reg===4)?STRUCT:tcol(Eng.T[regionTempKey[reg]]);
    for(let v=0;v<3;v++){const idx=(tri*3+v)*3;
      M.col[idx]=col.r;M.col[idx+1]=col.g;M.col[idx+2]=col.b;}
  }
  M.geo.attributes.color.needsUpdate=true;
}
function paint(){paintMesh(baseM);paintMesh(plateM);}
// ---------- UI ----------
const sI=document.getElementById('sI'),sS=document.getElementById('sS'),sR=document.getElementById('sR');
sI.oninput=()=>document.getElementById('vI').innerText=(+sI.value).toFixed(1)+' A';
sS.oninput=()=>document.getElementById('vS').innerText=sS.value+'x';
sR.oninput=()=>document.getElementById('vR').innerText=sR.value+' mm';
document.getElementById('reset').onclick=()=>{for(const k in Eng.T)Eng.T[k]=Eng.Tfar;Eng.Tair=Eng.Tfar;Eng.t=0;};
const setTxt=(id,v)=>document.getElementById(id).innerHTML=v.toFixed(1)+' &deg;C';
const setBox=(id,T)=>document.getElementById(id).style.background='#'+tcol(T).getHexString();
let last=performance.now();
function loop(){requestAnimationFrame(loop);
  const now=performance.now();let d=(now-last)/1000;last=now;if(d>0.1)d=0.1;
  const I=+sI.value,speed=+sS.value,R=+sR.value;
  const sub=20,dt=d*speed/sub;
  for(let i=0;i<sub;i++)Eng.step(I,R,dt);
  // payload 3D: radius from slider (scale X/Z = radial; Y = height, stays 1)
  payload.scale.set(R/PL.R_ref_mm,1,R/PL.R_ref_mm);
  payMat.color.copy(tcol(Eng.T.payload));
  // environment haze warms with the air node
  scene.fog.color.copy(FOG_BASE).lerp(FOG_HOT,Math.max(0,Math.min(1,(Eng.Tair-25)/40)));
  document.getElementById('vT').innerText=Eng.t.toFixed(0)+' s';
  document.getElementById('vP').innerText=Eng.power(I,R).toFixed(1)+' W';
  setTxt('tP',Eng.T.plate); setTxt('tPl',Eng.T.payload); setTxt('tI',Eng.T.inner);
  setTxt('tO',Eng.T.outer); setTxt('tFe',Eng.T.iron);   setTxt('tAir',Eng.Tair);
  setBox('bP',Eng.T.plate); setBox('bPl',Eng.T.payload); setBox('bI',Eng.T.inner);
  setBox('bO',Eng.T.outer); setBox('bFe',Eng.T.iron);   setBox('bAir',Eng.Tair);
  paint();controls.update();renderer.render(scene,camera);
}
addEventListener('resize',()=>{renderer.setSize(innerWidth,innerHeight);
  camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();});
loop();
</script></body></html>"""


if __name__ == "__main__":
    stl = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "3D_model.stl")
    out = os.path.join(ROOT, "digital_twin.html")
    build(stl, out)
