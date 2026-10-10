"""Mild dark-channel dehazing candidates; no learned weights or geometry changes.

Engineering adaptation, not a reproduction of Camera Raw. Quality groups are
appearance proxies, not confirmed weather labels.
"""
import cv2
import numpy as np
from .enhancement import quality

MODES=('dehaze_mild','dehaze_mix','dehaze_adaptive')
PARAMETERS=dict(patch=15,omega=.35,min_transmission=.65,airlight_min=.5,
                guided_radius=12,guided_eps=.001,mix=.3,
                contrast_threshold=.13,dark_channel_threshold=.18,
                highlights_limit=.08)

def dark_channel(rgb):
    minimum=rgb.min(axis=2)
    return cv2.erode(minimum,np.ones((PARAMETERS['patch'],)*2,np.uint8))

def guided_filter(guide,transmission):
    kernel=(2*PARAMETERS['guided_radius']+1,)*2
    def mean(x):
        return cv2.boxFilter(x,-1,kernel,normalize=True,borderType=cv2.BORDER_REFLECT)
    gmean,tmean=mean(guide),mean(transmission)
    variance=mean(guide*guide)-gmean*gmean
    covariance=mean(guide*transmission)-gmean*tmean
    a=covariance/(np.maximum(variance,0)+PARAMETERS['guided_eps'])
    b=tmean-a*gmean
    return mean(a)*guide+mean(b)

def appearance(rgb):
    stats=quality(rgb)
    proxy=rgb
    longest=max(rgb.shape[:2])
    if longest>320:
        proxy=cv2.resize(rgb,(max(1,round(rgb.shape[1]*320/longest)),
                             max(1,round(rgb.shape[0]*320/longest))))
    stats['dark_channel_mean']=float(dark_channel(proxy.astype(np.float32)/255).mean())
    if stats['highlights']>=PARAMETERS['highlights_limit']:
        group='highlights'
    elif stats['mean']<.32:
        group='dark'
    elif stats['contrast']<PARAMETERS['contrast_threshold']:
        group='low_contrast'
    else:
        group='ordinary'
    return dict(group=group,**stats)

def enhance(rgb,mode):
    if mode not in MODES:
        raise ValueError(mode)
    if rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
        raise ValueError('Expected uint8 RGB')
    stats=appearance(rgb)
    # Uniform/black inputs contain no recoverable contrast. Avoid artificial colours.
    bypass=stats['contrast']<.005 or stats['mean']<.02
    if mode=='dehaze_adaptive':
        bypass |= not (stats['group']=='low_contrast' and
                       stats['dark_channel_mean']>PARAMETERS['dark_channel_threshold'])
    if bypass:
        return rgb.copy(),dict(selected='original',quality=stats)
    image=rgb.astype(np.float32)/255
    dark=dark_channel(image)
    count=max(1,int(dark.size*.001))
    indices=np.argpartition(dark.ravel(),-count)[-count:]
    pixels=image.reshape(-1,3)[indices]
    air=np.maximum(pixels[np.argmax(pixels.mean(axis=1))],PARAMETERS['airlight_min'])
    transmission=1-PARAMETERS['omega']*dark_channel(image/air)
    gray=cv2.cvtColor(image,cv2.COLOR_RGB2GRAY)
    transmission=guided_filter(gray,transmission).clip(PARAMETERS['min_transmission'],1)
    recovered=((image-air)/transmission[:,:,None]+air).clip(0,1)
    mix=1. if mode=='dehaze_mild' else PARAMETERS['mix']
    # Avoid maximum-strength edits in nearly saturated pixels. This is a heuristic,
    # not a claim that lost highlight details can be reconstructed.
    protection=np.clip((image.max(axis=2)-.85)/.15,0,1)
    strength=mix*(1-.8*protection)
    result=np.rint((image+strength[:,:,None]*(recovered-image))*255).clip(0,255).astype(np.uint8)
    assert result.shape==rgb.shape
    return result,dict(selected=mode,quality=stats,airlight=air.tolist(),
                       transmission_min=float(transmission.min()),mix=mix)
