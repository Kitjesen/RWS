"""
RWS Tactical Tracking Demo — v2  (FAST & ACTION-PACKED)

Timeline (600 frames @ 30 fps = 20 s):
  0:00 – 0:05  SEARCH sweep + 3 fast targets emerge simultaneously
  0:05 – 0:15  Rapid lock → 3-kill sequence (one every ~3 s)
  0:15 – 0:20  Wave-2: 4 targets, 2 gimbals, dual simultaneous kills
  Final        Mission debrief
"""

import math, os, subprocess, tempfile, time
from typing import Optional, Tuple, List

import cv2
import numpy as np

# ─────────────────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 720
FPS           = 30
TOTAL_FRAMES  = 310          # ~10 seconds, hyper-dense action
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
C_PURPLE  = (180,   0, 180)
C_DKGREEN = (  0,  80,   0)
C_TEAL    = (160, 200,   0)

FONT   = cv2.FONT_HERSHEY_SIMPLEX
F_XS   = 0.36
F_SM   = 0.44
F_MD   = 0.58
F_LG   = 0.80
F_XL   = 1.20

# ─────────────────────────────────────────────────────────
# Precomputed assets
# ─────────────────────────────────────────────────────────

def _make_bg() -> np.ndarray:
    bg = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    for y in range(HEIGHT):
        t = y / HEIGHT
        bg[y, :] = (int(10 + t*6), int(14 + t*8), int(20 + t*12))
    rng = np.random.default_rng(7)
    bg = np.clip(bg.astype(np.int16) + rng.integers(0,8,(HEIGHT,WIDTH,3),np.uint8)-4,
                 0, 255).astype(np.uint8)
    # Horizon hills
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
    d = np.sqrt(((X-cx)/cx)**2 + ((Y-cy)/cy)**2)
    return (1.0 - np.clip(d*0.70, 0,1)**1.6).astype(np.float32)

def _make_grid() -> np.ndarray:
    """Tactical grid overlay (pre-rendered, alpha-blended once per frame)."""
    g = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    for x in range(0, WIDTH, 80):
        cv2.line(g, (x,0),(x,HEIGHT),(0,30,0),1)
    for y in range(0, HEIGHT, 80):
        cv2.line(g, (0,y),(WIDTH,y),(0,30,0),1)
    return g

_BG  = _make_bg()
_VIG = _make_vignette()
_GRID= _make_grid()


def get_frame_bg(f: int) -> np.ndarray:
    bg   = _BG.copy()
    rng  = np.random.default_rng(f*13+7)
    noise= rng.integers(0,5,(HEIGHT,WIDTH,3),np.uint8)
    bg   = np.clip(bg.astype(np.int16)+noise-2,0,255).astype(np.uint8)
    # grid
    cv2.addWeighted(bg, 1.0, _GRID, 0.35, 0, bg)
    return bg

def apply_vignette(frame: np.ndarray) -> None:
    v3 = np.stack([_VIG]*3, axis=2)
    np.multiply(frame, v3, out=frame, casting='unsafe')
    np.clip(frame, 0, 255, out=frame)

def draw_scanlines(frame: np.ndarray) -> None:
    frame[1::2] = (frame[1::2].astype(np.float32)*0.92).astype(np.uint8)


# ─────────────────────────────────────────────────────────
# Smooth GimbalAim
# ─────────────────────────────────────────────────────────

class GimbalAim:
    def __init__(self, x: float, y: float):
        self.x, self.y = float(x), float(y)

    def update(self, tx: float, ty: float, tau: float = 0.45) -> Tuple[int,int]:
        self.x += tau*(tx-self.x);  self.y += tau*(ty-self.y)
        return int(self.x), int(self.y)


# ─────────────────────────────────────────────────────────
# Target definitions
# ─────────────────────────────────────────────────────────
# Each target: id, label, conf, enter_frame, x0,y0, vx,vy,
#              wobble_amp, wobble_period, w, h, exit_frame
# vx/vy in px per frame (FAST: 4-8 px/f)

class Target:
    def __init__(self, tid, label, conf, enter, exit_f,
                 x0, y0, vx, vy, wx, wy, wp, w, h):
        self.tid   = tid;   self.label = label; self.conf  = conf
        self.enter = enter; self.exit  = exit_f
        self.x0,self.y0   = x0, y0
        self.vx,self.vy   = vx, vy
        self.wx,self.wy,self.wp = wx, wy, wp
        self.w,self.h     = w, h

    def pos(self, f:int) -> Optional[Tuple[int,int,int,int,float,float]]:
        if not (self.enter <= f < self.exit):
            return None
        t = f - self.enter
        x = int(self.x0 + self.vx*t + self.wx*math.sin(2*math.pi*t/max(self.wp,1)))
        y = int(self.y0 + self.vy*t + self.wy*math.cos(2*math.pi*t/max(self.wp,1)))
        return x, y, self.w, self.h, self.vx, self.vy


# ── Wave 1 (frames 15–90): 3 fast targets, G0 handles T1+T3, G1 handles T2
W1 = [
    # Person A — diagonal upper-left → lower-right, zigzag
    Target(1,"Person", 0.91, 15, 90,  80,120,  5.2, 3.2,  12,8, 22,  76,116),
    # Vehicle — right edge → left, fast, slight weave
    Target(2,"Vehicle",0.78, 15, 95, 1180,340, -6.5, 0.8,   0,14,40, 130, 78),
    # Person B — bottom → up-right, jinking
    Target(3,"Person", 0.85, 15,100,  600,620,  2.8,-5.0,  16,0, 18,  72,112),
]

# ── Wave 2 (frames 120–240): 4 targets simultaneously, two gimbals
W2 = [
    Target(4,"Person", 0.89, 120,230,  50,200,  6.0, 2.5,  10,6, 28,  80,120),
    Target(5,"Vehicle",0.72, 120,240,1220,420,  -7.5, 1.2,   0,10,35, 140, 82),
    Target(6,"Person", 0.83, 130,245, 640, 50,  1.5, 5.8,  14,0, 24,  74,114),
    Target(7,"Drone",  0.76, 130,250, 200,500,  5.0,-4.5,   8,8, 20,  60, 60),
]

ALL_TARGETS = W1 + W2


# ─────────────────────────────────────────────────────────
# Engagement schedule
# Tuple: (fire_frame, track_id, cx_at_fire, cy_at_fire)
# ─────────────────────────────────────────────────────────

# Wave 1 fires — rapid sequential every ~20 frames
FIRE_EVENTS: List[dict] = [
    dict(f=38,  tid=1),
    dict(f=58,  tid=2),
    dict(f=78,  tid=3),
    # Wave 2 — dual simultaneous kills
    dict(f=148, tid=4),
    dict(f=150, tid=5),
    dict(f=193, tid=6),
    dict(f=195, tid=7),
]
_NEUTRALIZED: set = set()

def is_neutralized(tid:int, f:int) -> bool:
    for ev in FIRE_EVENTS:
        if ev['tid']==tid and f >= ev['f']:
            return True
    return False


# ─────────────────────────────────────────────────────────
# Per-frame derived state
# ─────────────────────────────────────────────────────────

def _smooth(val, target, tau): return val + tau*(target-val)

# Track state per target
_TRACK_HISTORY: dict = {}   # tid → list of (cx,cy)

def get_target_state(tid:int, f:int) -> str:
    """Returns TRACK/LOCK/NEUTRALIZED/SEARCH."""
    for ev in FIRE_EVENTS:
        if ev['tid']==tid and f >= ev['f']:
            return "NEUTRALIZED"
    for tgt in ALL_TARGETS:
        if tgt.tid==tid:
            if tgt.enter <= f < tgt.exit:
                appear = f - tgt.enter
                if appear < 5: return "TRACK"
                return "LOCK"
    return "SEARCH"

def yaw_err_for(tid:int, f:int) -> float:
    """Simulate per-target yaw error (fast convergence)."""
    for tgt in ALL_TARGETS:
        if tgt.tid==tid:
            appear = f - tgt.enter
            if appear < 0: return 0.0
            if appear < 5:
                return 3.5*math.exp(-appear*0.55)+0.2
            t2 = appear - 5
            return 0.2*math.exp(-t2*0.55)+0.03
    return 0.0

def chain_state_at(f:int) -> str:
    for ev in FIRE_EVENTS:
        if ev['f']-3 <= f < ev['f']:    return "ARMED"
        if ev['f']   <= f < ev['f']+2:  return "FIRE_AUTH"
        if ev['f']+2 <= f < ev['f']+5:  return "FIRED"
    return "SAFE"

def fire_flash_intensity(f:int) -> Tuple[float,int,int,int]:
    """Returns (intensity, offset, cx, cy) for current flash, or 0 if none."""
    for ev in FIRE_EVENTS:
        ff = ev['f']
        if ff <= f < ff+10:
            offset = f - ff
            intensity = max(0.0, 1.0-(offset*0.12))
            cx, cy = WIDTH//2, HEIGHT//2
            for tgt in ALL_TARGETS:
                if tgt.tid == ev['tid']:
                    p = tgt.pos(ff)
                    if p: cx, cy = p[0]+p[2]//2, p[1]+p[3]//2
            return intensity, offset, cx, cy
    return 0.0, 0, 0, 0

# Kill notification queue: list of (expire_frame, tid, label)
_KILL_NOTES: List[dict] = []
for ev in FIRE_EVENTS:
    for tgt in ALL_TARGETS:
        if tgt.tid == ev['tid']:
            _KILL_NOTES.append(dict(f=ev['f'], expire=ev['f']+45,
                                    tid=ev['tid'], label=tgt.label))


# ─────────────────────────────────────────────────────────
# Drawing helpers
# ─────────────────────────────────────────────────────────

def _rect_filled_alpha(frame, x1,y1,x2,y2, color=(0,0,0), alpha=0.65):
    ov = frame.copy()
    cv2.rectangle(ov,(x1,y1),(x2,y2),color,-1)
    cv2.addWeighted(ov,alpha,frame,1-alpha,0,frame)


def draw_hud_header(frame, f:int, active_tgts:list, chain:str):
    n_lock  = sum(1 for t,_ in active_tgts if get_target_state(t.tid,f)=="LOCK")
    n_track = sum(1 for t,_ in active_tgts if get_target_state(t.tid,f)=="TRACK")
    n_total = len(active_tgts)
    fps_str = f"RWS v2.0  |  {f:04d}  |  30.0 FPS"
    tgt_str = f"Targets: {n_total} active  |  Lock: {n_lock}  Track: {n_track}"
    chain_str=f"Chain: {chain}"
    _rect_filled_alpha(frame, 6,6,480,82, alpha=0.55)
    cv2.putText(frame,fps_str,(12,26),FONT,F_SM,C_GREEN,1,cv2.LINE_AA)
    cv2.putText(frame,tgt_str,(12,48),FONT,F_SM,C_GREEN,1,cv2.LINE_AA)
    cv2.putText(frame,chain_str,(12,70),FONT,F_SM,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(0,88),(WIDTH,88),(0,90,0),1)


def draw_threat_table(frame, active_tgts:list, f:int):
    """Right-side threat table with per-target rows."""
    if not active_tgts: return
    px, py = WIDTH-200, 100
    rows = min(len(active_tgts), 6)
    ph   = 26 + rows*26
    _rect_filled_alpha(frame, px,py, px+192, py+ph, alpha=0.70)
    cv2.rectangle(frame,(px,py),(px+192,py+ph),C_GREEN,1)
    cv2.putText(frame,"THREAT QUEUE",(px+8,py+17),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(px,py+22),(px+192,py+22),C_GREEN,1)

    sorted_tgts = sorted(active_tgts, key=lambda x: -x[1])  # sort by threat desc
    for i,(tgt, threat) in enumerate(sorted_tgts[:6]):
        ty    = py+38+i*26
        state = get_target_state(tgt.tid, f)
        if state=="LOCK":    tc=C_GREEN
        elif state=="TRACK": tc=C_YELLOW
        else:                tc=C_GRAY
        err = yaw_err_for(tgt.tid, f)
        row = f"#{tgt.tid:<2} {tgt.label[:7]:<7} {threat:.2f}  {err:.1f}deg"
        cv2.putText(frame,row,(px+6,ty),FONT,F_XS,tc,1,cv2.LINE_AA)
        # mini threat bar
        bx = px+162;  bw=24
        fill=int(bw*min(threat,1.0))
        cv2.rectangle(frame,(bx,ty-9),(bx+bw,ty-2),(40,40,40),-1)
        bar_c = C_RED if threat>0.7 else (C_ORANGE if threat>0.4 else C_GREEN)
        if fill>0: cv2.rectangle(frame,(bx,ty-9),(bx+fill,ty-2),bar_c,-1)


def draw_fire_chain_panel(frame, chain:str, f:int):
    px,py=WIDTH-200,320; pw,ph=192,145
    _rect_filled_alpha(frame,px,py,px+pw,py+ph,alpha=0.70)
    cv2.rectangle(frame,(px,py),(px+pw,py+ph),C_GREEN,1)
    cv2.putText(frame,"FIRE CHAIN",(px+8,py+17),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)
    cv2.line(frame,(px,py+22),(px+pw,py+22),C_GREEN,1)
    order=[("SAFE","SAFE"),("ARMED","ARMED"),("FIRE_AUTH","FIRE AUTH"),("FIRED","FIRED")]
    for i,(key,lbl) in enumerate(order):
        ty=py+40+i*26; active=(chain==key)
        if active and key=="ARMED":
            flash=(f//7)%2==0; dc=C_ORANGE if flash else C_GRAY; tc=C_ORANGE if flash else C_GRAY
        elif active and key=="FIRE_AUTH":
            flash=(f//3)%2==0; dc=C_RED if flash else (120,0,0); tc=C_RED if flash else C_GRAY
        elif active and key=="FIRED": dc=C_WHITE;tc=C_WHITE
        elif active:               dc=C_GREEN;tc=C_GREEN
        else:                      dc=C_GRAY;tc=(50,50,50)
        cv2.circle(frame,(px+14,ty),5,dc,-1 if active else 1,cv2.LINE_AA)
        cv2.putText(frame,lbl,(px+26,ty+4),FONT,F_XS,tc,1,cv2.LINE_AA)


def draw_reticle(frame, cx:int,cy:int, state:str, color:tuple, f:int):
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
        # Pulsing filled dot
        pr=int(4+2*math.sin(f*0.4))
        cv2.circle(frame,(cx,cy),pr,color,-1,cv2.LINE_AA)
        # Rotating tick marks
        for k in range(4):
            a=math.radians(k*90+(f*3)%360)
            ix=int(cx+(R-12)*math.cos(a)); iy=int(cy+(R-12)*math.sin(a))
            ox=int(cx+(R- 4)*math.cos(a)); oy=int(cy+(R- 4)*math.sin(a))
            cv2.line(frame,(ix,iy),(ox,oy),color,2,cv2.LINE_AA)


def draw_bbox(frame, x,y,w,h, tgt:Target, state:str, alloc:str, f:int, trail=None):
    if state in ("SEARCH","NEUTRALIZED"): return
    color = C_GREEN if state=="LOCK" else C_YELLOW
    cv2.rectangle(frame,(x,y),(x+w,y+h),color,2)
    # Corner ticks
    tl=14
    for (ax,ay),(bx,by) in [((x,y),(x+tl,y)),((x,y),(x,y+tl)),
                              ((x+w,y),(x+w-tl,y)),((x+w,y),(x+w,y+tl)),
                              ((x,y+h),(x+tl,y+h)),((x,y+h),(x,y+h-tl)),
                              ((x+w,y+h),(x+w-tl,y+h)),((x+w,y+h),(x+w,y+h-tl))]:
        cv2.line(frame,(ax,ay),(bx,by),color,2,cv2.LINE_AA)
    # Label
    err  = yaw_err_for(tgt.tid,f)
    lbl  = f"#{tgt.tid} {tgt.label} {tgt.conf:.2f}"
    cv2.putText(frame,lbl,(x,max(y-6,14)),FONT,F_SM,color,1,cv2.LINE_AA)
    # Error indicator
    err_c= C_GREEN if err<1.0 else (C_ORANGE if err<2.5 else C_RED)
    cv2.putText(frame,f"{err:.2f}deg",(x+w+4,y+12),FONT,F_XS,err_c,1,cv2.LINE_AA)
    # Alloc
    if alloc:
        cv2.putText(frame,alloc,(x+w//2-12,y+h+16),FONT,F_SM,C_CYAN,1,cv2.LINE_AA)
    # Velocity arrow
    cx2,cy2=x+w//2,y+h//2
    evx=int(cx2+tgt.vx*10); evy=int(cy2+tgt.vy*10)
    if abs(evx-cx2)+abs(evy-cy2)>3:
        cv2.arrowedLine(frame,(cx2,cy2),(evx,evy),color,1,cv2.LINE_AA,tipLength=0.3)
    # Trail
    if trail:
        for i,(tx,ty2) in enumerate(trail[-12:]):
            a = (i+1)/13.0
            tc= tuple(int(c*a) for c in color)
            cv2.circle(frame,(tx,ty2),2,tc,-1,cv2.LINE_AA)


def draw_crosshair(frame, ax:int, ay:int, color:tuple, alpha:float=0.55):
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
    flash_c= C_WHITE if offset==0 else (100,180,255)
    a = 0.75*intensity if offset==0 else 0.5*intensity
    ov=np.full_like(frame,flash_c,np.uint8)
    cv2.addWeighted(ov,a,frame,1-a,0,frame)
    for ring in range(4):
        r=int((offset*55+ring*40)*intensity)
        if r>0:
            ar=max(0.0,1.0-offset*0.14-ring*0.20)
            rp=frame.copy()
            cv2.circle(rp,(cx,cy),r,C_ORANGE,3,cv2.LINE_AA)
            cv2.addWeighted(rp,ar,frame,1-ar,0,frame)


def draw_fire_text(frame, intensity:float):
    if intensity<=0: return
    txt="FIRE EXECUTED"
    (tw,th),_=cv2.getTextSize(txt,FONT,F_XL,3)
    tx=(WIDTH-tw)//2; ty=HEIGHT//2+th//2
    ov=frame.copy()
    cv2.putText(ov,txt,(tx,ty),FONT,F_XL,C_RED,3,cv2.LINE_AA)
    cv2.addWeighted(ov,intensity,frame,1-intensity,0,frame)


def draw_kill_notifications(frame, f:int):
    visible=[n for n in _KILL_NOTES if n['f']<=f<n['expire']]
    for i,n in enumerate(visible[:4]):
        age=f-n['f']; fade=max(0.0,1.0-age/45.0)
        txt=f"  KILL  #{n['tid']} {n['label']}"
        x=WIDTH-260; y=HEIGHT-90-i*30
        _rect_filled_alpha(frame,x-4,y-18,x+250,y+6,(40,0,0),0.65*fade)
        c=tuple(int(v*fade) for v in C_RED)
        cv2.putText(frame,txt,(x,y),FONT,F_MD,c,1,cv2.LINE_AA)


def draw_status_bar(frame, primary_state:str, chain:str,
                     primary_tid:int, yaw_e:float, pitch_e:float, f:int):
    by=HEIGHT-36
    _rect_filled_alpha(frame,0,by,WIDTH,HEIGHT,alpha=0.72)
    cv2.line(frame,(0,by),(WIDTH,by),(0,90,0),1)
    # State pill
    if chain=="FIRE_AUTH":
        fl=(f//3)%2==0; pc=C_RED if fl else (60,0,0); pt="[ FIRE AUTHORIZED ]"; tc=C_WHITE if fl else C_RED
    elif chain=="FIRED":
        pc=(230,230,230); pt=f"[ FIRE EXECUTED #{primary_tid} ]"; tc=(0,0,0)
    elif chain=="ARMED":
        fl=(f//7)%2==0; pc=C_ORANGE if fl else (50,35,0); pt="[ ARMED ]"; tc=C_WHITE if fl else C_ORANGE
    elif primary_state=="LOCK":
        pc=(0,90,0); pt=f"[ LOCKED #{primary_tid} ]"; tc=C_GREEN
    elif primary_state=="TRACK":
        pc=(55,55,0); pt=f"[ TRACKING #{primary_tid} ]"; tc=C_YELLOW
    else:
        pc=(35,35,35); pt="[ SCANNING ]"; tc=C_GRAY
    (tw,th),_=cv2.getTextSize(pt,FONT,F_SM,1)
    cv2.rectangle(frame,(8,by+4),(8+tw+14,by+th+12),pc,-1)
    cv2.putText(frame,pt,(15,by+th+8),FONT,F_SM,tc,1,cv2.LINE_AA)
    # PID bars
    _err_bar(frame,WIDTH-280,by+7,130,11,yaw_e,"Yaw")
    _err_bar(frame,WIDTH-280,by+21,130,11,pitch_e,"Pitch")


def _err_bar(frame,x,y,w,h,err,lbl):
    r=min(abs(err)/5.0,1.0); fw=int(w*r)
    bc=C_GREEN if err<1.0 else (C_ORANGE if err<3.0 else C_RED)
    cv2.rectangle(frame,(x,y),(x+w,y+h),(45,45,45),-1)
    if fw>0: cv2.rectangle(frame,(x,y),(x+fw,y+h),bc,-1)
    cv2.rectangle(frame,(x,y),(x+w,y+h),C_GRAY,1)
    cv2.putText(frame,f"{lbl} {err:.2f}°",(x-115,y+h-1),FONT,F_XS,C_GREEN,1,cv2.LINE_AA)


def draw_wave2_header(frame):
    txt="MULTI-GIMBAL ENGAGEMENT  —  G0 + G1 ACTIVE"
    (tw,_),_=cv2.getTextSize(txt,FONT,F_MD,1)
    cv2.putText(frame,txt,((WIDTH-tw)//2,112),FONT,F_MD,C_CYAN,1,cv2.LINE_AA)


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
        ("  Duration","10.3s"),
        ("  Targets tracked","7"),
        ("  Shots fired","7"),
        ("  Lock rate","94%"),
        ("  Avg yaw error","0.18°"),
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

    # Write to a lossless AVI first (MJPG is reliable on all platforms),
    # then re-encode with ffmpeg to H.264 MP4 so FPS is always correct.
    tmp_avi = output_path.replace(".mp4", "_tmp.avi")
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(tmp_avi, fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        # Fallback: try direct mp4v
        tmp_avi = output_path
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open VideoWriter: {output_path}")

    print(f"Rendering {TOTAL_FRAMES} frames → {output_path}")

    aim: dict[int,GimbalAim] = {0:GimbalAim(WIDTH//2,HEIGHT//2),
                                  1:GimbalAim(WIDTH//2,HEIGHT//2)}
    trails: dict[int, list]   = {}
    t0=time.time()

    for f in range(TOTAL_FRAMES):
        frame = get_frame_bg(f)
        draw_scanlines(frame)

        # ── Active targets this frame
        active_raw=[]
        for tgt in ALL_TARGETS:
            p=tgt.pos(f)
            if p and not is_neutralized(tgt.tid,f):
                active_raw.append((tgt,p))

        # Assign gimbals: wave1 → G0 on T1/T3, G1 on T2
        #                 wave2 → G0 on T4/T6, G1 on T5/T7
        G0_TIDS={1,3,4,6}; G1_TIDS={2,5,7}

        # Build threat scores
        active_tgts=[]
        for tgt,p in active_raw:
            appear=f-tgt.enter
            threat=min(0.95, 0.3+appear*0.012+tgt.conf*0.2)
            active_tgts.append((tgt,threat))

        # ── Search sweep when no targets
        if f<15 or (not active_raw and f<130):
            draw_search_sweep(frame,f)

        # ── Draw targets
        primary_tid=0; primary_state="SEARCH"; primary_yaw=0.0; primary_pitch=0.0

        for tgt,(x,y,w,h,vx,vy) in active_raw:
            cx2,cy2=x+w//2,y+h//2
            state=get_target_state(tgt.tid,f)
            is_g0=(tgt.tid in G0_TIDS)
            alloc="G0" if is_g0 else "G1"
            rc=C_CYAN if is_g0 else C_MAGENTA

            # Trail
            if tgt.tid not in trails: trails[tgt.tid]=[]
            trails[tgt.tid].append((cx2,cy2))
            if len(trails[tgt.tid])>20: trails[tgt.tid].pop(0)

            draw_bbox(frame,x,y,w,h,tgt,state,alloc,f,trails.get(tgt.tid,[]))
            draw_reticle(frame,cx2,cy2,state,rc,f)

            # Gimbal convergence
            gid=0 if is_g0 else 1
            tau=0.58 if state=="LOCK" else 0.42
            gx,gy=aim[gid].update(cx2,cy2,tau)
            draw_crosshair(frame,gx,gy,rc,0.50)

            # Pick primary (highest threat, G0 preferred)
            for tgt2,threat2 in active_tgts:
                if tgt2.tid==tgt.tid:
                    if is_g0 and (primary_tid==0 or threat2>0.5):
                        primary_tid=tgt.tid
                        primary_state=state
                        primary_yaw=yaw_err_for(tgt.tid,f)
                        primary_pitch=primary_yaw*0.58

        if not active_raw:
            aim[0].update(WIDTH//2,HEIGHT//2,0.04)
            aim[1].update(WIDTH//2,HEIGHT//2,0.04)

        # ── Fire flash
        fl_int,fl_off,fl_cx,fl_cy=fire_flash_intensity(f)
        if fl_int>0:
            draw_fire_flash(frame,fl_int,fl_off,fl_cx,fl_cy)
        # Fire text
        for ev in FIRE_EVENTS:
            if ev['f']<=f<ev['f']+25:
                draw_fire_text(frame,max(0.0,1.0-(f-ev['f'])/25.0))
                break

        # Kill notifications
        draw_kill_notifications(frame,f)

        # Wave 2 banner
        if any(tgt.tid>=4 for tgt,_ in active_raw):
            draw_wave2_header(frame)

        # Mission summary
        if f>=240:
            draw_mission_summary(frame,f,240)

        # HUD
        chain=chain_state_at(f)
        draw_hud_header(frame,f,active_tgts,chain)
        draw_threat_table(frame,active_tgts,f)
        draw_fire_chain_panel(frame,chain,f)
        draw_status_bar(frame,primary_state,chain,primary_tid,
                        primary_yaw,primary_pitch,f)

        apply_vignette(frame)
        writer.write(frame)

        if f%60==0:
            el=time.time()-t0
            eta=(el/max(f,1))*(TOTAL_FRAMES-f)
            print(f"  {f:4d}/{TOTAL_FRAMES} ({f/TOTAL_FRAMES*100:5.1f}%)  "
                  f"elapsed {el:5.1f}s  ETA {eta:.1f}s")

    writer.release()
    el=time.time()-t0

    # If we used tmp AVI, re-encode with ffmpeg → guaranteed correct FPS
    if tmp_avi != output_path:
        print(f"\nRe-encoding with ffmpeg → H.264 @ {FPS}fps …")
        ret = subprocess.run([
            "ffmpeg", "-y",
            "-r", str(FPS),          # input fps
            "-i", tmp_avi,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-r", str(FPS),          # output fps (force)
            "-movflags", "+faststart",
            output_path,
        ], capture_output=True, text=True)
        if ret.returncode != 0:
            print("ffmpeg error:", ret.stderr[-800:])
            raise RuntimeError("ffmpeg failed")
        os.remove(tmp_avi)

    sz=os.path.getsize(output_path)
    print(f"\nSaved: {output_path}  "
          f"({TOTAL_FRAMES} frames, {TOTAL_FRAMES/FPS:.1f}s, "
          f"{sz/1024/1024:.1f} MB)  render {el:.1f}s")


if __name__=="__main__":
    render_video(OUTPUT_PATH)
