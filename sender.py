#!/usr/bin/python3

import time, sys, os, math, socket, argparse, cv2, threading
import numpy as np
from utils.transformer import Transform,deTransform
from utils.pkg_generator import sendPackage
from utils.imresize import imresize
import PIL.Image as pil_image
from PIL import Image




''' DEFINE ARGUMENT PARSER'''
TRUE = ["True","true",'t','T','1']
FALSE = ["False",'false''f','F','0']
SR_METHODS = ['sr','fsrcnn','vdsr','edsr','carn']
parser = argparse.ArgumentParser()
parser.add_argument("--method", type=str,choices=["sr","fsrcnn", "hr",'vdsr','edsr','carn'], default="sr")
parser.add_argument("--host", type=str, default="localhost")
parser.add_argument("--port", type=int, default=1112)
parser.add_argument("--image_width", type=int, default=1280)
parser.add_argument("--image_height", type=int, default=960)
parser.add_argument("--use_saved_video", type=str,choices=TRUE+FALSE, default="True")
parser.add_argument("--video", type=str, default='./dataset/Video/people.mp4')
parser.add_argument("--video_maxframe", type=int, default=100)
parser.add_argument("--scale", type=int, default=4)
parser.add_argument("--nthread", type=int, default=8)
parser.add_argument("--jpg_quality", type=int, default=100)
parser.add_argument("--max_sender_fps", type=float, default=1/24)
parser.add_argument("--max_video_fps", type=float, default=1/24)
parser.add_argument("--sock_buff_size", type=int, default=40480)
parser.add_argument("--verbose", type=str,choices=TRUE+FALSE, default='True')
cfg = parser.parse_args()
    
''' CREATE SOCKET '''
SOCK_CONN   = None
SOCK_CONN   = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
SOCK_CONN.settimeout(1)
SOCK_CONN.connect((cfg.host, cfg.port))
bufsize = SOCK_CONN.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
print("Initialized socket {}:{} ...".format(cfg.host, cfg.port))
print("Socket sending buffer size = ", bufsize)
EXIT = False

NUM_BYTES = 0
NUM_FRAME = 0
STATS = [-1.0,-1.0,-1.0]
GAMMA = 0.01

CAP = None
FRAME = np.zeros((cfg.image_height,cfg.image_width,3),dtype=np.uint8)

def VideoReader():
    global FRAME, CAP,cfg

    '''
    A function for update video at "cfg.max_video_fps" frame per second.
    The video repeat every "cfg.video_maxframe" frames.
    The updated frame is stored in FRAME.
    '''

    nframe = 0
    while(1):
        t_begin = time.perf_counter()
        CAP = (cv2.VideoCapture(cfg.video) if cfg.use_saved_video in TRUE else cv2.VideoCapture(0)) if nframe == 0 else CAP
        FRAME   = cv2.resize(CAP.read()[1], (cfg.image_width,cfg.image_height))
        nframe = 0 #if nframe >= cfg.video_maxframe else nframe + 1
        t_end   = time.perf_counter()
        time.sleep(cfg.max_video_fps - (t_end - t_begin)) if t_end - t_begin < (cfg.max_video_fps) else None
        sys.exit() if EXIT else None

''' START A THREAD FOR UPDATING VIDEO'''
thread  = threading.Thread(target=VideoReader)
thread.start()


while(1):
    t_begin = time.perf_counter()
    ''' TRANSFORM EACH FRAME TO LOW-RESOLUTION IMAGE & HIGH-RESOLUTION CROPPED IMAGE'''
    if cfg.method == 'fsrcnn':
        frame = np.array(Image.fromarray(FRAME).resize((cfg.image_width//cfg.scale,cfg.image_height//cfg.scale), resample=pil_image.BICUBIC))
    elif cfg.method in ['vdsr','edsr','carn']:
        frame = cv2.resize(FRAME, (cfg.image_width//cfg.scale,cfg.image_height//cfg.scale),interpolation=cv2.INTER_LINEAR)
        #frame = imresize(FRAME,scalar_scale=0.25)
    elif cfg.method in ['sr']:
        frame = cv2.resize(FRAME, (cfg.image_width//cfg.scale,cfg.image_height//cfg.scale),interpolation=cv2.INTER_LINEAR)
    else:
        frame = FRAME
    centre = FRAME[FRAME.shape[0]//4:3*FRAME.shape[0]//4,FRAME.shape[1]//4:3*FRAME.shape[1]//4,:] if cfg.method in SR_METHODS else None
                
    ''' SEND THE PACKAGES/IMAGES'''
    NUM_BYTES += sendPackage(SOCK_CONN,centre,cfg,start_pkg_num=0) if centre is not None else 0
    NUM_BYTES += sendPackage(SOCK_CONN,frame,cfg,start_pkg_num=cfg.nthread)

    cv2.imshow('x',frame)
    img_jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, cfg.jpg_quality])[1] # convert to jpg
    cv2.imwrite('original.png',cv2.imdecode(img_jpeg, cv2.IMREAD_COLOR) )
    if cv2.waitKey(1) & 0xff == 27:
        print("Esc is pressed.\nExit")
        SOCK_CONN.close()
        cv2.destroyAllWindows()
        EXIT = True
        sys.exit()

    ''' REDUCE SPEED'''
    t_end   = time.perf_counter()
    time.sleep(cfg.max_sender_fps - (t_end - t_begin)) if t_end - t_begin < (cfg.max_sender_fps) else None

    if cfg.verbose in TRUE:
        NUM_FRAME += 1
        t = (time.perf_counter()-t_begin)
        STATS[0] = (1.0-GAMMA)*STATS[0] + GAMMA*(1e-6*NUM_BYTES/t) if STATS[0] >= 0.0 else (1e-6*NUM_BYTES/t)
        STATS[1] = (1.0-GAMMA)*STATS[1] + GAMMA*(1.0/t) if STATS[1] >= 0.0 else (1.0/t)
        STATS[2] = (1.0-GAMMA)*STATS[2] + GAMMA*(1e-3*NUM_BYTES) if STATS[2] >= 0.0 else (1e-3*NUM_BYTES)
        NUM_BYTES = 0
        if NUM_FRAME %100 == 0:
            print('---------------------------------------------------------------')
            print('Throughput',STATS[0],'MBps')
            print('Frame Rate', STATS[1], 'FPS')
            print('Size',STATS[2],'KB')
            NUM_FRAME = 0