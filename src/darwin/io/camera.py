from .video import OpenCVCamera, VideoCamera

def make_camera(config):
    args=dict(width=config.camera_width,height=config.camera_height,fps=config.camera_fps)
    if config.camera_backend=='video':
        if not config.camera_path: raise ValueError('video path required')
        return VideoCamera(config.camera_path,**args)
    if config.camera_backend=='webcam': return OpenCVCamera(config.camera_index,**args)
    if config.camera_backend=='oak':
        from .oak import OakCamera
        return OakCamera(**args)
    raise ValueError('camera backend must be oak, webcam, or video; simulation renderer is runtime-owned')
