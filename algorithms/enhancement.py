"""Conservative RGB-only transforms. No geometry, labels or model weights change."""
import numpy as np
import cv2

MODES=('original','gamma_light','gamma_dark','clahe','adaptive')
PARAMETERS=dict(gamma_light=.85,gamma_dark=1.15,mix=.3,clip_limit=1.3,
                tiles=8,dark_mean=.32,bright_mean=.68,low_contrast=.13,
                highlight_limit=.08)

def quality(rgb):
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    return dict(mean=float(gray.mean()),contrast=float(gray.std()),
                highlights=float((gray>.95).mean()),shadows=float((gray<.05).mean()))

def enhance(rgb,mode):
    if mode not in MODES:
        raise ValueError(mode)
    if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
        raise ValueError('Expected uint8 HxWx3 RGB')
    stats=quality(rgb)
    selected=mode
    if mode=='adaptive':
        # Heuristic starting thresholds, to be validated, not learned from test data.
        if stats['mean']<PARAMETERS['dark_mean'] and stats['highlights']<PARAMETERS['highlight_limit']:
            selected='gamma_light'
        elif stats['mean']>PARAMETERS['bright_mean']:
            selected='gamma_dark'
        elif stats['contrast']<PARAMETERS['low_contrast'] and stats['highlights']<PARAMETERS['highlight_limit']:
            selected='clahe'
        else:
            selected='original'
    if selected=='original':
        return rgb.copy(),dict(selected=selected,quality=stats)
    if selected.startswith('gamma'):
        gamma=PARAMETERS[selected]
        lut=np.rint((np.arange(256,dtype=np.float32)/255)**gamma*255).astype(np.uint8)
        processed=cv2.LUT(rgb,lut)
    else:
        lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
        lab[:,:,0]=cv2.createCLAHE(clipLimit=PARAMETERS['clip_limit'],
            tileGridSize=(PARAMETERS['tiles'],)*2).apply(lab[:,:,0])
        processed=cv2.cvtColor(lab,cv2.COLOR_LAB2RGB)
    mixed=np.rint(rgb.astype(np.float32)*(1-PARAMETERS['mix'])+
                  processed.astype(np.float32)*PARAMETERS['mix']).clip(0,255).astype(np.uint8)
    assert mixed.shape==rgb.shape
    return mixed,dict(selected=selected,quality=stats)
