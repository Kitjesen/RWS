"""
RWS Tactical Tracking Demo — v3  (REAL GIMBAL BEHAVIOUR)

Timeline (~8 s @ 30 fps):
  0:00 – 0:05  Wave-1: G0 acquires T1 (high-threat), G1 acquires T2 simultaneously
               Both fire, G0 slews to T3 while G1 idles → G0 fires T3
  0:05 – 0:08  Wave-2: 4 targets flood in, G0/G1 each work through ordered queue
               T4/T5 killed together, G0 slews→T6, G1 slews→T7, both fire
  Final        Mission debrief overlay

Key behaviours demonstrated:
  • Gimbal NEVER teleports — physically slews between targets (visible trail)
  • Priority queue: highest-threat target engaged first
  • TRACK phase (12 frames): tau ramps 0.08→0.30 — crosshair visibly accelerates
  • LOCK phase: tau=0.72 — tight tracking with natural lag on fast targets
  • Lead-angle dot shown during LOCK (white diamond ahead of velocity vector)
  • Engagement-plan panel: G0 / G1 queues with live ✓ checkmarks
  • "NEXT→Tn" dashed line shows planning intent while current target is live
"""

import math, os, subprocess, time
from typing import Optional, Tuple, List

import cv2
import numpy as np

# ─────────────────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 720
FPS           = 30
TOTAL_FRAMES  = 230
OUTPUT_PATH   = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs", "tracking_demo.mp4",
)

# HUD colours (BGR)
C_GREEN   = (  0, 220,   0)
C_LGREEN  = ( 80, 255,  80)
C_YELLOW  = (  0, 220, 220)
C_RED     = ( 30,  30, 220)
C_CYAN    = (220, 220,   0)
C_ORANGE  = (  0, 140, 255)
C_WHITE   = (255, 255, 255)
C_GRAY    = (120, 120, 120)
C_MAGENTA = (220,   0, 220)
C_DKGRAY  = ( 50,  50,  50)

FONT = cv2.FONT_HERSHEY_SIMPLEX
F_XS = 0.36
F_SM = 0.44
F_MD = 0.58
F_LG = 0.80
F_XL = 1.20

# ─────────────────────────────────────────────────────────
# Pre-computed scene assets
# ─────────────────────────────────────────────────────────

def _make_bg() -> np.ndarray:
    bg = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    for y in range(HEIGHT):
        t = y / HEIGHT
        bg[y, :] = (int(10+t*6), int(14+t*8), int(20+t*12))
    rng = np.random.default_rng(7)
    bg = np.clip(bg.astype(np.int16)+rng.integers(0,8,(HEIGHT,WIDTH,3),np.uint8)-4,
                 0, 255).astype(np.uint8)
    for pts, c in [
        ([(0,495),(220,455),(440,475),(660,428),(880,460),(1100,445),(1280,468),(1280,720),(0,720)],
         (12,18,14)),
        ([(0,535),(280,508),(520,528),(740,504),(960,522),(1200,498),(1280,518),(1280,720),(0,720)],
         (8,12,10)),
    ]:
        cv2.fillPoly(bg, [np.array(pts, np.int32)], c)
    return bg

def _make_vignette() -> np.ndarray:
    cx, cy = WIDTH//2, HEIGHT//2
    Y, X   = np.mgrid[0:HEIGHT, 0:WIDTH]
    d = np.sqrt(((X-cx)/cx)**2+((Y-cy)/cy)**2)
    return (1.0-np.clip(d*0.70, 0,1)**1.6).astype(np.float32)

def _make_grid() -> np.ndarray:
    g = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    for x in range(0, WIDTH, 80): cv2.line(g,(x,0),(x,HEIGHT),(0,28,0),1)
    for y in range(0, HEIGHT, 80): cv2.line(g,(0,y),(WIDTH,y),(0,28,0),1)
    return g

_BG  = _make_bg()
_VIG = _make_vignette()
_GRID= _make_grid()

def get_frame_bg(f:int) -> np.ndarray:
    bg   = _BG.copy()
    rng  = np.random.default_rng(f*13+7)
    noise= rng.integers(0,5,(HEIGHT,WIDTH,3),np.uint8)
    bg   = np.clip(bg.astype(np.int16)+noise-2,0,255).astype(np.uint8)
    cv2.addWeighted(bg,1.0,_GRID,0.32,0,bg)
    return bg

def apply_vignette(frame:np.ndarray) -> None:
    v3 = np.stack([_VIG]*3, axis=2)
    np.multiply(frame, v3, out=frame, casting='unsafe')
    np.clip(frame, 0, 255, out=frame)

def draw_scanlines(frame:np.ndarray) -> None:
    frame[1::2] = (frame[1::2].astype(np.float32)*0.92).astype(np.uint8)


# ─────────────────────────────────────────────────────────
# Gimbal model
# ─────────────────────────────────────────────────────────

class GimbalAim:
    def __init__(self, x:float, y:float):
        self.x, self.y = float(x), float(y)

    def update(self, tx:float, ty:float, tau:float=0.20) -> Tuple[int,int]:
        self.x += tau*(tx-self.x)
        self.y += tau*(ty-self.y)
        return int(self.x), int(self.y)


# ─────────────────────────────────────────────────────────
# Target definitions  — FAST (9-13 px/frame)
# ─────────────────────────────────────────────────────────

class Target:
    def __init__(self, tid, label, conf, enter, exit_f,
                 x0, y0, vx, vy, wx, wy, wp, w, h):
        self.tid=tid;  self.label=label;  self.conf=conf
        self.enter=enter;  self.exit=exit_f
        self.x0,self.y0=x0,y0
        self.vx,self.vy=vx,vy
        self.wx,self.wy,self.wp=wx,wy,wp
        self.w,self.h=w,h

    def pos(self, f:int) -> Optional[Tuple[int,int,int,int,float,float]]:
        if not (self.enter <= f < self.exit): return None
        t = f-self.enter
        x = int(self.x0+self.vx*t+self.wx*math.sin(2*math.pi*t/max(self.wp,1)))
        y = int(self.y0+self.vy*t+self.wy*math.cos(2*math.pi*t/max(self.wp,1)))
        return x, y, self.w, self.h, self.vx, self.vy

# Wave-1: 3 targets, all fast, enter at frame 15
# Wave-2: 4 targets enter at 105-112, gimbals re-engage immediately
W1 = [
    Target(1,"Person", 0.91, 15, 60,   80,130,  9.5, 4.2,  10,8, 20,  76,116),
    Target(2,"Vehicle",0.78, 15, 60, 1180,340, -11.5, 1.5,   0,12,38, 130, 78),
    Target(3,"Person", 0.85, 15, 90,  610,620,   5.5,-10.5, 14,0, 16,  72,112),
]
W2 = [
    Target(4,"Person", 0.89, 105,150,  60,190,  10.5, 3.8,  8,6, 24,  80,120),
    Target(5,"Vehicle",0.72, 105,150, 1230,410, -13.0, 2.0,  0,8, 32, 140, 82),
    Target(6,"Person", 0.83, 112,175,  640, 45,   2.0,10.5, 12,0, 20,  74,114),
    Target(7,"Drone",  0.76, 112,178,  190,505,  10.0,-8.5,  6,6, 18,  60, 60),
]
ALL_TARGETS = W1 + W2

# ─────────────────────────────────────────────────────────
# Engagement schedule
# Each gimbal works a priority queue, ONE target at a time.
#   G0 queue: T1 → T3 → T4 → T6
#   G1 queue: T2      → T5 → T7
#
# GIMBAL_ACQUIRE[gid][tid] = frame at which gimbal gid starts tracking tid
#   (= fire_frame of previous target + 1, or target enter frame if first)
# ─────────────────────────────────────────────────────────

GIMBAL_QUEUES: dict = {
    0: [1, 3, 4, 6],
    1: [2, 5, 7],
}

# Precomputed acquisition frames (derive from fire schedule below)
# T1/T2 acquired at enter (15); fire at 15+12+18=45
# T3: G0 acquires at 46 (T1 killed@45); fire at 46+12+18=76
# T4/T5: G0/G1 acquire at 105 (wave-2 enter); fire at 105+12+18=135
# T6/T7: G0/G1 acquire at 136 (T4/T5 killed@135); fire at 136+12+18=166

GIMBAL_ACQUIRE: dict = {
    0: {1: 15,  3: 46,  4: 105, 6: 136},
    1: {2: 15,         5: 105, 7: 136},
}

FIRE_EVENTS: List[dict] = [
    dict(f=45,  tid=1),
    dict(f=45,  tid=2),
    dict(f=76,  tid=3),
    dict(f=135, tid=4),
    dict(f=135, tid=5),
    dict(f=166, tid=6),
    dict(f=166, tid=7),
]

def is_neutralized(tid:int, f:int) -> bool:
    for ev in FIRE_EVENTS:
        if ev['tid']==tid and f>=ev['f']: return True
    return False


# ─────────────────────────────────────────────────────────
# Gimbal-aware state and error queries
# ─────────────────────────────────────────────────────────

def get_primary_for_gimbal(gid:int, f:int) -> Optional[Target]:
    """Return the current (non-neutralized, acquired) target for gimbal gid."""
    for tid in GIMBAL_QUEUES[gid]:
        acq = GIMBAL_ACQUIRE[gid].get(tid)
        if acq is None or f < acq: continue
        if is_neutralized(tid, f): continue
        for tgt in ALL_TARGETS:
            if tgt.tid==tid and tgt.enter<=f<tgt.exit:
                return tgt
    return None

def get_next_for_gimbal(gid:int, f:int) -> Optional[Target]:
    """Return the next target in queue after the current primary."""
    found = False
    for tid in GIMBAL_QUEUES[gid]:
        if found:
            for tgt in ALL_TARGETS:
                if tgt.tid==tid: return tgt  # may not be visible yet — that's OK
        acq = GIMBAL_ACQUIRE[gid].get(tid)
        if acq is None or f<acq: continue
        if is_neutralized(tid, f): found=True; continue
        for tgt in ALL_TARGETS:
            if tgt.tid==tid and tgt.enter<=f<tgt.exit:
                found=True; break
    return None

def gimbal_appear(gid:int, tid:int, f:int) -> int:
    """Frames since gimbal gid acquired target tid (0 if not yet acquired)."""
    acq = GIMBAL_ACQUIRE[gid].get(tid, 99999)
    return max(0, f-acq)

def gimbal_state(gid:int, f:int) -> str:
    """SEARCH / TRACK / LOCK for gimbal gid."""
    for tid in GIMBAL_QUEUES[gid]:
        acq = GIMBAL_ACQUIRE[gid].get(tid, 99999)
        if f<acq: continue
        if is_neutralized(tid, f): continue
        for tgt in ALL_TARGETS:
            if tgt.tid==tid and tgt.enter<=f<tgt.exit:
                ap = f-acq
                return "TRACK" if ap<12 else "LOCK"
    return "SEARCH"

def gimbal_yaw_err(gid:int, f:int) -> float:
    for tid in GIMBAL_QUEUES[gid]:
        acq = GIMBAL_ACQUIRE[gid].get(tid, 99999)
        if f<acq: continue
        if is_neutralized(tid, f): continue
        for tgt in ALL_TARGETS:
            if tgt.tid==tid and tgt.enter<=f<tgt.exit:
                ap = f-acq
                if ap<12: return 4.0*math.exp(-ap*0.22)+0.5
                return 0.5*math.exp(-(ap-12)*0.45)+0.04
    return 0.0

def chain_state_at(f:int) -> str:
    for ev in FIRE_EVENTS:
        if ev['f']-3<=f<ev['f']:   return "ARMED"
        if ev['f']<=f<ev['f']+2:   return "FIRE_AUTH"
        if ev['f']+2<=f<ev['f']+5: return "FIRED"
    return "SAFE"

def fire_flash_at(f:int) -> Tuple[float,int,int,int]:
    for ev in FIRE_EVENTS:
        ff=ev['f']
        if ff<=f<ff+10:
            off=f-ff; intensity=max(0.0,1.0-off*0.12)
            cx,cy=WIDTH//2,HEIGHT//2
            for tgt in ALL_TARGETS:
                if tgt.tid==ev['tid']:
                    p=tgt.pos(ff)
                    if p: cx,cy=p[0]+p[2]//2,p[1]+p[3]//2
            return intensity,off,cx,cy
    return 0.0,0,0,0

_KILL_NOTES: List[dict] = []
for _ev in FIRE_EVENTS:
    for _tgt in ALL_TARGETS:
        if _tgt.tid==_ev['tid']:
            _KILL_NOTES.append(dict(f=_ev['f'], expire=_ev['f']+48,
                                    tid=_ev['tid'], label=_tgt.label))


# ─────────────────────────────────────────────────────────
# Drawing helpers
# ─────────────────────────────────────────────────────────

def _rect_alpha(frame, x1,y1,x2,y2, color=(0,0,0), alpha=0.65):
    ov=frame.copy(); cv2.rectangle(ov,(x1,y1),(x2,y2),color,-1)
    cv2.addWeighted(ov,alpha,frame,1-alpha,0,frame)

def _draw_dashed_line(frame, x1,y1, x2,y2, color, dash=10, alpha=0.45):
    """Draw a dashed line from (x1,y1) to (x2,y2)."""
    dx,dy = x2-x1, y2-y1
    length = max(1, int(math.hypot(dx,dy)))
    ov=frame.copy()
    for i in range(0, length, dash*2):
        t0=i/length; t1=min((i+dash)/length,1.0)
        px0=int(x1+dx*t0); py0=int(y1+dy*t0)
        px1=int(x1+dx*t1); py1=int(y1+dy*t1)
        cv2.line(ov,(px0,py0),(px1,py1),color,1,cv2.LINE_AA)
    cv2.addWeighted(ov,alpha,frame,1-alpha,0,frame)

def draw_reticle(frame, cx:int, cy:int, state:str, color:tuple, f:int):
    R=58; ri=7; g1=13; g2=52
    if state=="SEARCH":
        ang=(f*9)%360
        ex=int(cx+R*math.cos(math.radians(ang)))
        ey=int(cy+R*math.sin(math.radians(ang)))
        cv2.circle(frame,(cx,cy),R,C_RED,1,cv2.LINE_AA)
        cv2.line(frame,(cx,cy),(ex,ey),C_RED,1,cv2.LINE_AA)
        return
    cv2.circle(frame,(cx,cy),R,color,1,cv2.LINE_AA)
    cv2.circle(frame,(cx,cy),ri,color,1,cv2.LINE_AA)
    for dx,dy in [(0,-1),(0,1),(-1,0),(1,0)]:
        cv2.line(frame,(cx+dx*g1,cy+dy*g1),(cx+dx*g2,cy+dy*g2),color,1,cv2.LINE_AA)
    blen=16; boff=R+7
    for sx,sy in [(-1,-1),(1,-1),(1,1),(-1,1)]:
        bx=cx+sx*boff; by=cy+sy*boff
        cv2.line(frame,(bx,by),(bx+sx*blen,by),color,1,cv2.LINE_AA)
        cv2.line(frame,(bx,by),(bx,by+sy*blen),color,1,cv2.LINE_AA)
    if state=="LOCK":
        pr=int(4+2*math.sin(f*0.4))
        cv2.circle(frame,(cx,cy),pr,color,-1,cv2.LINE_AA)
        for k in range(4):
            a=math.radians(k*90+(f*3)%360)
            ix=int(cx+(R-12)*math.cos(a)); iy=int(cy+(R-12)*math.sin(a))
            ox=int(cx+(R-4)*math.cos(a));  oy=int(cy+(R-4)*math.sin(a))
            cv2.line(frame,(ix,iy),(ox,oy),color,2,cv2.LINE_AA)

def draw_bbox(frame, x,y,w,h, tgt:Target, state:str, alloc:str, err:float,
              f:int, trail=None):
    if state=="SEARCH": return
    color = C_GREEN if state=="LOCK" else C_YELLOW
    cv2.rectangle(frame,(x,y),(x+w,y+h),color,2)
    tl=14
    for (ax,ay),(bx,by) in [((x,y),(x+tl,y)),((x,y),(x,y+tl)),
                              ((x+w,y),(x+w-tl,y)),((x+w,y),(x+w,y+tl)),
                              ((x,y+h),(x+tl,y+h)),((x,y+h),(x,y+h-tl)),
                              ((x+w,y+h),(x+w-tl,y+h)),((x+w,y+h),(x+w,y+h-tl))]:
        cv2.line(frame,(ax,ay),(bx,by),color,2,cv2.LINE_AA)
    lbl=f"#{tgt.tid} {tgt.label} {tgt.conf:.2f}"
    cv2.putText(frame,lbl,(x,max(y-6,14)),FONT,F_SM,color,1,cv2.LINE_AA)
    err_c = C_GREEN if err<1.0 else (C_ORANGE if err<2.5 else C_RED)
    cv2.putText(frame,f"{err:.2f}deg",(x+w+4,y+12),FONT,F_XS,err_c,1,cv2.LINE_AA)
    if alloc:
        cv2.putText(frame,alloc,(x+w//2-12,y+h+16),FONT,F_SM,C_CYAN,1,cv2.LINE_AA)
    cx2,cy2=x+w//2,y+h//2
    evx=int(cx2+tgt.vx*10); evy=int(cy2+tgt.vy*10)
    if abs(evx-cx2)+abs(evy-cy2)>3:
        cv2.arrowedLine(frame,(cx2,cy2),(evx,evy),color,1,cv2.LINE_AA,tipLength=0.3)
    if trail:
        for i,(tx,ty2) in enumerate(trail[-14:]):
            a=(i+1)/15.0
            tc=tuple(int(c*a) for c in color)
            cv2.circle(frame,(tx,ty2),2,tc,-1,cv2.LINE_AA)

def draw_crosshair(frame, ax:int, ay:int, color:tuple, alpha:float=0.65):
    ov=frame.copy()
    cv2.line(ov,(ax,0),(ax,HEIGHT),color,1)
    cv2.line(ov,(0,ay),(WIDTH,ay),color,1)
    cv2.circle(ov,(ax,ay),5,color,1,cv2.LINE_AA)
    cv2.addWeighted(ov,alpha,frame,1-alpha,0,frame)

def draw_search_sweep(frame, f:int):
    cx,cy=WIDTH//2,HEIGHT//2
    ang=(f*5)%360; rad=math.radians(ang)
    length=max(WIDTH,HEIGHT)
    ex=int(cx+length*math.cos(rad)); ey=int(cy+length*math.sin(rad))
    ov=frame.copy()
    cv2.line(ov,(cx,cy),(ex,ey),(0,70,0),1)
    cv2.addWeighted(ov,0.45,frame,0.55,0,frame)
    for r in [120,250,400]:
        cv2.circle(frame,(cx,cy),r,(0,55,0),1,cv2.LINE_AA)
    cv2.circle(frame,(cx,cy),6,C_GREEN,-1,cv2.LINE_AA)
    cv2.putText(frame,"SCANNING...",(cx-55,cy-320),FONT,F_MD,C_GREEN,1,cv2.LINE_AA)

def draw_fire_flash(frame, intensity:float, offset:int, cx:int, cy:int):
    if intensity<=0: return
    flash_c=C_WHITE if offset==0 else (100,180,255)
    a=0.75*intensity if offset==0 else 0.5*intensity
    ov=np.full_like(frame,flash_c,np.uint8)
    cv2.addWeighted(ov,a,frame,1-a,0,frame)
    for ring in range(4):
        r=int((offset*55+ring*40)*intensity)
        if r>0:
            ar=max(0.0,1.0-offset*0.14-ring*0.20)
            rp=frame.copy()
            cv2.circle(rp,(cx,cy),r,C_ORANGE,3,cv2.LINE_AA)
            cv2.addWeighted(rp,ar,frame,1-ar,0,frame)

def draw_fire_text(frame, intensity:float, tid:int):
    if intensity<=0: return
    txt=f"FIRE EXECUTED — T{tid}"
    (tw,th),_=cv2.getTextSize(txt,FONT,F_XL,3)
    tx=(WIDTH-tw)//2; ty=HEIGHT//2+th//2
    ov=frame.copy()
    cv2.putText(ov,txt,(tx,ty),FONT,F_XL,C_RED,3,cv2.LINE_AA)
    cv2.addWeighted(ov,intensity,frame,1-intensity,0,frame)

def draw_kill_notifications(frame, f:int):
    visible=[n for n in _KILL_NOTES if n['f']<=f<n['expire']]
    for i,n in enumerate(visible[:4]):
        age=f-n['f']; fade=max(0.0,1.0-age/48.0)
        txt=f"  KILL  #{n['tid']} {n['label']}"
        x=WIDTH-260; y=HEIGHT-90-i*30
        _rect_alpha(frame,x-4,y-18,x+250,y+6,(40,0,0),0.65*fade)
        c=tuple(int(v*fade) for v in C_RED)
        cv2.putText(frame,txt,(x,y),FONT,F_MD,c,1,cv2.LINE_AA)


def draw_engagement_plan(frame, f:int):
    """Show G0/G1 engagement queues with live status."""
    px,py=8,HEIGHT-130; pw=390; ph=118
    _rect_alpha(frame,px,py,px+pw,py+ph,alpha=0.72)
    cv2.rectangle(frame,(px,py),(px+pw,py+ph),C_GREEN,1)
    cv2.putText(frame,"ENGAGEMENT PLAN",(px+8,py+16),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(px,py+21),(px+pw,py+21),C_GREEN,1)
    for row,gid in enumerate([0,1]):
        rc=C_CYAN if gid==0 else C_MAGENTA
        ty=py+38+row*36
        cv2.putText(frame,f"G{gid}:",(px+8,ty),FONT,F_SM,rc,1,cv2.LINE_AA)
        xoff=px+52
        for j,tid in enumerate(GIMBAL_QUEUES[gid]):
            acq=GIMBAL_ACQUIRE[gid].get(tid,99999)
            neutralized=is_neutralized(tid,f)
            is_primary=(acq<=f and not neutralized)
            is_future=(acq>f)
            is_killed=neutralized
            # Color and bracket style
            if is_killed:
                box_c=(50,50,50); txt_c=(60,60,60); prefix="✓"
            elif is_primary:
                fl=(f//5)%2==0
                box_c=C_GREEN if fl else (0,100,0); txt_c=C_WHITE; prefix="►"
            elif is_future:
                box_c=C_DKGRAY; txt_c=C_GRAY; prefix=""
            else:
                box_c=C_DKGRAY; txt_c=C_GRAY; prefix=""
            lbl=f"{prefix}T{tid}"
            (tw,th),_=cv2.getTextSize(lbl,FONT,F_SM,1)
            bx1=xoff-2; by1=ty-th-3; bx2=xoff+tw+6; by2=ty+4
            cv2.rectangle(frame,(bx1,by1),(bx2,by2),box_c,-1 if is_primary else 1)
            cv2.putText(frame,lbl,(xoff,ty),FONT,F_SM,txt_c,1,cv2.LINE_AA)
            xoff+=tw+18
            if j<len(GIMBAL_QUEUES[gid])-1:
                cv2.putText(frame,"→",(xoff-14,ty),FONT,F_XS,C_GRAY,1,cv2.LINE_AA)
                xoff+=2


def draw_hud_header(frame, f:int, n_active:int, n_lock:int, chain:str):
    fps_str=f"RWS v3.0  |  {f:04d}  |  30.0 FPS"
    tgt_str=f"Targets: {n_active} active  Lock: {n_lock}"
    chain_str=f"Chain: {chain}"
    _rect_alpha(frame,6,6,480,82,alpha=0.55)
    cv2.putText(frame,fps_str,(12,26),FONT,F_SM,C_GREEN,1,cv2.LINE_AA)
    cv2.putText(frame,tgt_str,(12,48),FONT,F_SM,C_GREEN,1,cv2.LINE_AA)
    cv2.putText(frame,chain_str,(12,70),FONT,F_SM,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(0,88),(WIDTH,88),(0,90,0),1)

def draw_threat_table(frame, active_tgts:list, f:int):
    if not active_tgts: return
    px,py=WIDTH-200,100
    rows=min(len(active_tgts),7)
    ph=26+rows*24
    _rect_alpha(frame,px,py,px+192,py+ph,alpha=0.70)
    cv2.rectangle(frame,(px,py),(px+192,py+ph),C_GREEN,1)
    cv2.putText(frame,"THREAT QUEUE",(px+8,py+17),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(px,py+22),(px+192,py+22),C_GREEN,1)
    for i,(tgt,threat) in enumerate(sorted(active_tgts,key=lambda x:-x[1])[:7]):
        ty=py+36+i*24
        gs=gimbal_state(0 if tgt.tid in GIMBAL_QUEUES[0] else 1, f)
        gid=0 if tgt.tid in GIMBAL_QUEUES[0] else 1
        # Is this the primary for its gimbal?
        prim=get_primary_for_gimbal(gid,f)
        if prim and prim.tid==tgt.tid:
            tc=C_GREEN if gs=="LOCK" else C_YELLOW
        else:
            tc=C_GRAY
        err=gimbal_yaw_err(gid,f) if (prim and prim.tid==tgt.tid) else 0.0
        row=f"#{tgt.tid:<2} {tgt.label[:7]:<7} {threat:.2f}"
        cv2.putText(frame,row,(px+6,ty),FONT,F_XS,tc,1,cv2.LINE_AA)
        bx=px+162; bw=24
        fill=int(bw*min(threat,1.0))
        cv2.rectangle(frame,(bx,ty-9),(bx+bw,ty-2),(40,40,40),-1)
        bar_c=C_RED if threat>0.7 else (C_ORANGE if threat>0.4 else C_GREEN)
        if fill>0: cv2.rectangle(frame,(bx,ty-9),(bx+fill,ty-2),bar_c,-1)

def draw_fire_chain_panel(frame, chain:str, f:int):
    px,py=WIDTH-200,320; pw,ph=192,145
    _rect_alpha(frame,px,py,px+pw,py+ph,alpha=0.70)
    cv2.rectangle(frame,(px,py),(px+pw,py+ph),C_GREEN,1)
    cv2.putText(frame,"FIRE CHAIN",(px+8,py+17),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(px,py+22),(px+pw,py+22),C_GREEN,1)
    order=[("SAFE","SAFE"),("ARMED","ARMED"),("FIRE_AUTH","FIRE AUTH"),("FIRED","FIRED")]
    for i,(key,lbl) in enumerate(order):
        ty=py+40+i*26; active=(chain==key)
        if active and key=="ARMED":
            fl=(f//7)%2==0; dc=C_ORANGE if fl else C_GRAY; tc=C_ORANGE if fl else C_GRAY
        elif active and key=="FIRE_AUTH":
            fl=(f//3)%2==0; dc=C_RED if fl else (120,0,0); tc=C_RED if fl else C_GRAY
        elif active and key=="FIRED": dc=C_WHITE; tc=C_WHITE
        elif active: dc=C_GREEN; tc=C_GREEN
        else: dc=C_GRAY; tc=(50,50,50)
        cv2.circle(frame,(px+14,ty),5,dc,-1 if active else 1,cv2.LINE_AA)
        cv2.putText(frame,lbl,(px+26,ty+4),FONT,F_XS,tc,1,cv2.LINE_AA)

def draw_status_bar(frame, chain:str, primary_tid:int, yaw_e:float,
                    pitch_e:float, f:int):
    by=HEIGHT-36
    _rect_alpha(frame,0,by,WIDTH,HEIGHT,alpha=0.72)
    cv2.line(frame,(0,by),(WIDTH,by),(0,90,0),1)
    g0s=gimbal_state(0,f); g1s=gimbal_state(1,f)
    if chain=="FIRE_AUTH":
        fl=(f//3)%2==0; pc=C_RED if fl else (60,0,0)
        pt="[ FIRE AUTHORIZED ]"; tc=C_WHITE if fl else C_RED
    elif chain=="FIRED":
        pc=(230,230,230); pt=f"[ FIRE EXECUTED T{primary_tid} ]"; tc=(0,0,0)
    elif chain=="ARMED":
        fl=(f//7)%2==0; pc=C_ORANGE if fl else (50,35,0)
        pt="[ ARMED ]"; tc=C_WHITE if fl else C_ORANGE
    elif g0s=="LOCK" or g1s=="LOCK":
        pc=(0,90,0); pt=f"[ LOCKED T{primary_tid} ]"; tc=C_GREEN
    elif g0s=="TRACK" or g1s=="TRACK":
        pc=(55,55,0); pt=f"[ ACQUIRING T{primary_tid} ]"; tc=C_YELLOW
    else:
        pc=(35,35,35); pt="[ SCANNING ]"; tc=C_GRAY
    (tw,th),_=cv2.getTextSize(pt,FONT,F_SM,1)
    cv2.rectangle(frame,(8,by+4),(8+tw+14,by+th+12),pc,-1)
    cv2.putText(frame,pt,(15,by+th+8),FONT,F_SM,tc,1,cv2.LINE_AA)
    _err_bar(frame,WIDTH-280,by+7,130,11,yaw_e,"Yaw")
    _err_bar(frame,WIDTH-280,by+21,130,11,pitch_e,"Pitch")

def _err_bar(frame,x,y,w,h,err,lbl):
    r=min(abs(err)/5.0,1.0); fw=int(w*r)
    bc=C_GREEN if err<1.0 else (C_ORANGE if err<3.0 else C_RED)
    cv2.rectangle(frame,(x,y),(x+w,y+h),(45,45,45),-1)
    if fw>0: cv2.rectangle(frame,(x,y),(x+fw,y+h),bc,-1)
    cv2.rectangle(frame,(x,y),(x+w,y+h),C_GRAY,1)
    cv2.putText(frame,f"{lbl} {err:.2f}°",(x-115,y+h-1),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)

def draw_mission_summary(frame, f:int, start:int):
    age=f-start; fade=min(1.0,age/20.0)
    ow,oh=int(WIDTH*0.58),int(HEIGHT*0.58)
    ox=(WIDTH-ow)//2; oy=(HEIGHT-oh)//2
    ov=frame.copy()
    cv2.rectangle(ov,(ox,oy),(ox+ow,oy+oh),(0,0,0),-1)
    cv2.addWeighted(ov,0.82*fade,frame,1-0.82*fade,0,frame)
    cv2.rectangle(frame,(ox,oy),(ox+ow,oy+oh),C_GREEN,2)
    stats=[
        ("═"*38,""),
        ("     MISSION DEBRIEF",""),
        ("═"*38,""),
        ("  Duration","7.7s"),
        ("  Targets tracked","7"),
        ("  Shots fired","7"),
        ("  Lock rate","100%"),
        ("  Avg yaw error","0.12°"),
        ("  Max threat","0.91"),
        ("  Chain integrity","SHA-256 ✓"),
        ("═"*38,""),
    ]
    for i,(k,v) in enumerate(stats):
        ty=oy+38+i*28
        c=C_GREEN if v else (0,140,0)
        a=min(1.0,max(0.0,(age-(i*2))/15.0))
        line=k if not v else f"{k:<28}{v}"
        ov2=frame.copy()
        cv2.putText(ov2,line,(ox+18,ty),FONT,F_SM,c,1,cv2.LINE_AA)
        cv2.addWeighted(ov2,a,frame,1-a,0,frame)


# ─────────────────────────────────────────────────────────
# Main render
# ─────────────────────────────────────────────────────────

def render_video(output_path:str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    tmp_avi = output_path.replace(".mp4","_tmp.avi")
    fourcc  = cv2.VideoWriter_fourcc(*"MJPG")
    writer  = cv2.VideoWriter(tmp_avi, fourcc, FPS, (WIDTH,HEIGHT))
    if not writer.isOpened():
        tmp_avi = output_path
        writer  = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"),
                                   FPS, (WIDTH,HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open VideoWriter: {output_path}")

    print(f"Rendering {TOTAL_FRAMES} frames → {output_path}")

    aim: dict       = {0: GimbalAim(WIDTH//2, HEIGHT//2),
                       1: GimbalAim(WIDTH//2, HEIGHT//2)}
    trails: dict    = {}           # target motion trails
    aim_trails:dict = {0:[], 1:[]} # gimbal crosshair trails
    t0 = time.time()

    for f in range(TOTAL_FRAMES):
        frame = get_frame_bg(f)
        draw_scanlines(frame)

        # ── Visible active targets (not neutralized)
        active_raw = []
        for tgt in ALL_TARGETS:
            p = tgt.pos(f)
            if p and not is_neutralized(tgt.tid, f):
                active_raw.append((tgt, p))

        # ── Search sweep (no active targets)
        if f<15 or (not active_raw and f<120):
            draw_search_sweep(frame, f)

        # ── Wave-2 banner
        if any(tgt.tid>=4 for tgt,_ in active_raw):
            txt="MULTI-GIMBAL ENGAGEMENT  —  G0 + G1 ACTIVE"
            (tw,_),_=cv2.getTextSize(txt,FONT,F_MD,1)
            cv2.putText(frame,txt,((WIDTH-tw)//2,112),FONT,F_MD,C_CYAN,1,cv2.LINE_AA)

        # ── Per-gimbal targeting
        gimbal_cx: dict = {}  # gid → (cx,cy) of primary target this frame
        for gid in [0, 1]:
            rc = C_CYAN if gid==0 else C_MAGENTA
            primary = get_primary_for_gimbal(gid, f)

            if primary:
                p = primary.pos(f)
                if p:
                    cx2,cy2 = p[0]+p[2]//2, p[1]+p[3]//2
                    ap = gimbal_appear(gid, primary.tid, f)
                    state = "TRACK" if ap<12 else "LOCK"
                    # Variable tau: ramp during TRACK, tight during LOCK
                    tau = (0.08 + min(ap,11)*0.022) if state=="TRACK" else 0.72
                    gx,gy = aim[gid].update(cx2, cy2, tau)
                    gimbal_cx[gid] = (cx2,cy2)
                else:
                    gx,gy = int(aim[gid].x), int(aim[gid].y)
            else:
                # No active target — slew back toward center
                gx,gy = aim[gid].update(WIDTH//2, HEIGHT//2, 0.04)

            # Gimbal trail (shows physical slew path)
            aim_trails[gid].append((int(aim[gid].x), int(aim[gid].y)))
            if len(aim_trails[gid])>22: aim_trails[gid].pop(0)
            for i,(tx2,ty2) in enumerate(aim_trails[gid][:-1]):
                a=(i+1)/len(aim_trails[gid])
                tc=tuple(int(c*a*0.60) for c in rc)
                cv2.circle(frame,(tx2,ty2),2,tc,-1,cv2.LINE_AA)

            draw_crosshair(frame, int(aim[gid].x), int(aim[gid].y), rc, 0.65)

            # "NEXT→Tn" dashed-line planning indicator
            if primary:
                nxt = get_next_for_gimbal(gid, f)
                if nxt:
                    np2 = nxt.pos(f)
                    if np2:
                        nx,ny = np2[0]+np2[2]//2, np2[1]+np2[3]//2
                        _draw_dashed_line(frame,
                                          int(aim[gid].x), int(aim[gid].y),
                                          nx, ny, rc, alpha=0.35)
                        cv2.putText(frame,f"NEXT→T{nxt.tid}",
                                    (nx,max(ny-26,14)),FONT,F_XS,rc,1,cv2.LINE_AA)

        # ── Draw all visible target boxes + reticles
        active_tgts_scored = []
        for tgt,(x,y,w,h,vx,vy) in active_raw:
            cx2,cy2 = x+w//2, y+h//2
            gid = 0 if tgt.tid in GIMBAL_QUEUES[0] else 1
            rc  = C_CYAN if gid==0 else C_MAGENTA
            acq = GIMBAL_ACQUIRE[gid].get(tgt.tid, 99999)
            if acq<=f and not is_neutralized(tgt.tid,f):
                ap    = f-acq
                state = "TRACK" if ap<12 else "LOCK"
                err   = gimbal_yaw_err(gid, f) if (get_primary_for_gimbal(gid,f) and
                                                    get_primary_for_gimbal(gid,f).tid==tgt.tid) else 0.0
            else:
                state = "SEARCH"
                err   = 0.0

            # Target motion trail
            if tgt.tid not in trails: trails[tgt.tid]=[]
            trails[tgt.tid].append((cx2,cy2))
            if len(trails[tgt.tid])>26: trails[tgt.tid].pop(0)

            draw_bbox(frame,x,y,w,h,tgt,state,f"G{gid}",err,f,trails.get(tgt.tid,[]))
            draw_reticle(frame,cx2,cy2,state,rc,f)

            # ACQ progress bar during TRACK
            if state=="TRACK":
                ap  = f-acq
                prog= int((ap/12.0)*10)
                bar ="█"*prog+"░"*(10-prog)
                cv2.putText(frame,f"ACQ [{bar}]",(x,max(y-22,14)),
                            FONT,F_XS,C_YELLOW,1,cv2.LINE_AA)

            # Lead-angle prediction dot during LOCK
            if state=="LOCK":
                lx=int(cx2+vx*9); ly=int(cy2+vy*9)
                cv2.circle(frame,(lx,ly),5,C_WHITE,1,cv2.LINE_AA)
                cv2.circle(frame,(lx,ly),2,C_WHITE,-1,cv2.LINE_AA)
                cv2.line(frame,(cx2,cy2),(lx,ly),C_WHITE,1,cv2.LINE_AA)

            ap2 = f-tgt.enter
            threat = min(0.95, 0.3+ap2*0.014+tgt.conf*0.2)
            active_tgts_scored.append((tgt,threat))

        # ── Fire effects
        fl_int,fl_off,fl_cx,fl_cy = fire_flash_at(f)
        if fl_int>0:
            draw_fire_flash(frame,fl_int,fl_off,fl_cx,fl_cy)
        active_fire_tid = 0
        for ev in FIRE_EVENTS:
            if ev['f']<=f<ev['f']+25:
                it = max(0.0,1.0-(f-ev['f'])/25.0)
                draw_fire_text(frame,it,ev['tid'])
                active_fire_tid=ev['tid']
                break

        draw_kill_notifications(frame,f)

        # ── HUD panels
        chain     = chain_state_at(f)
        n_lock    = sum(1 for gid in [0,1] if gimbal_state(gid,f)=="LOCK")
        p0        = get_primary_for_gimbal(0,f)
        p_tid     = p0.tid if p0 else (active_fire_tid or 0)
        yaw_e     = gimbal_yaw_err(0,f)
        pitch_e   = yaw_e*0.58
        draw_hud_header(frame,f,len(active_raw),n_lock,chain)
        draw_threat_table(frame,active_tgts_scored,f)
        draw_fire_chain_panel(frame,chain,f)
        draw_status_bar(frame,chain,p_tid,yaw_e,pitch_e,f)
        draw_engagement_plan(frame,f)

        if f>=185:
            draw_mission_summary(frame,f,185)

        apply_vignette(frame)
        writer.write(frame)

        if f%60==0:
            el=time.time()-t0
            eta=(el/max(f,1))*(TOTAL_FRAMES-f)
            print(f"  {f:4d}/{TOTAL_FRAMES} ({f/TOTAL_FRAMES*100:5.1f}%)"
                  f"  elapsed {el:4.1f}s  ETA {eta:.1f}s")

    writer.release()
    el=time.time()-t0

    if tmp_avi!=output_path:
        print(f"\nRe-encoding with ffmpeg → H.264 @ {FPS}fps …")
        ret=subprocess.run([
            "ffmpeg","-y","-r",str(FPS),"-i",tmp_avi,
            "-c:v","libx264","-preset","fast","-crf","18",
            "-r",str(FPS),"-movflags","+faststart",output_path,
        ], capture_output=True, text=True)
        if ret.returncode!=0:
            print("ffmpeg error:",ret.stderr[-800:])
            raise RuntimeError("ffmpeg failed")
        os.remove(tmp_avi)

    sz=os.path.getsize(output_path)
    print(f"\nSaved: {output_path}  "
          f"({TOTAL_FRAMES} frames, {TOTAL_FRAMES/FPS:.1f}s, "
          f"{sz/1024/1024:.1f} MB)  render {el:.1f}s")


if __name__=="__main__":
    render_video(OUTPUT_PATH)
