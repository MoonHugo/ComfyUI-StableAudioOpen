import os
import json
import time
import folder_paths
import torch
import torchaudio
from einops import rearrange
from stable_audio_tools import get_pretrained_model,create_model_from_config
from stable_audio_tools.models.utils import load_ckpt_state_dict
from stable_audio_tools.inference.generation import generate_diffusion_cond
from typing import TypedDict

current_path  = os.getcwd()
output_dir = folder_paths.get_output_directory();
output_dir = os.path.join(output_dir,"stable-audio-open-1.0")
## ComfyUI portable standalone build for Windows 
model_path = os.path.join(current_path, "ComfyUI"+os.sep+"models"+os.sep+"stable_audio_open")

os.makedirs(output_dir, exist_ok=True)
os.makedirs(model_path, exist_ok=True)

class AudioDict(TypedDict):
    sample_rate: int
    waveform: torch.Tensor


class Text2Audio:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": { 
                "prompt": ("STRING", {"default":"The sound of dog barking.","multiline":True}),
                "negative_prompt": ("STRING", {"default":"Low quality.","multiline":True,}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "steps": ("INT", {"default": 250, "min": 1, "max": 0xffffffffffffffff, "step": 1}),
                "cfg_scale": ("FLOAT", {
                    "default": 6.0,
                    "min": 0.0,
                    "max": 10.0,
                    "step": 0.01,
                    "round": 0.001, #The value representing the precision to round to, will be set to the step value by default. Can be set to False to disable rounding.
                    "display": "number",
                    "lazy": True
                }),
                "sampler_type": (["dpmpp-3m-sde", "dpmpp-2m-sde", "k-heun", "k-dpmpp-2s-ancestral", "k-dpm-2", "k-dpm-fast"], {"default": "dpmpp-3m-sde"}),
                "audio_length": ("INT",{"default":47,"min":0,"max":47}),
                "save_path": ("STRING", {"default":"",}),
                "load_local_model": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "local_model_path": ("STRING", {"default":model_path}),
            }
        }
    def cut(self, audio: AudioDict, length: float, offset: float):
        sample_rate = audio["sample_rate"]
        start_idx = int(offset * sample_rate / 1000)
        end_idx = min(
            start_idx + int(length * sample_rate / 1000),
            audio["waveform"].shape[-1],
        )
        cut_waveform = audio["waveform"][:, :, start_idx:end_idx]

        return (
            {
                "sample_rate": sample_rate,
                "waveform": cut_waveform,
            },
        )

    RETURN_TYPES = ("AUDIO","STRING")
    RETURN_NAMES = ("audio","audio_path")
    FUNCTION = "text2audio"
    OUTPUT_NODE = True
    CATEGORY = "🔥text2audio"
  
    def text2audio(self, prompt, negative_prompt,steps,cfg_scale,seed,sampler_type,audio_length,save_path,load_local_model, **kwargs):
        try:
            if save_path != "" and not os.path.isdir(save_path):
                raise ValueError("save_path："+save_path+"不是目录（output_path:"+save_path+" is not a directory）")
            local_model_path = kwargs.get("local_model_path", model_path)
            if local_model_path != "" and not os.path.isdir(local_model_path):
                raise ValueError("local_model_path："+local_model_path+"不是目录（output_path:"+local_model_path+" is not a directory）")
            
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if load_local_model:
                model_file = os.path.join(local_model_path, "model.safetensors")
                if not os.path.isfile(model_file):
                    raise ValueError("模型文件："+model_file+"不存在（model file:"+model_file+" does not exist）")
                with open(os.path.join(local_model_path,"model_config.json") , 'r') as f:
                    model_config = json.load(f)
                model = create_model_from_config(model_config)
                model.load_state_dict(load_ckpt_state_dict(model_file))
            else:
                # Download model
                model, model_config = get_pretrained_model("stabilityai/stable-audio-open-1.0")
            
            sample_rate = model_config["sample_rate"]
            sample_size = model_config["sample_size"]
            model = model.to(device)
            # Set up text and timing conditioning
            conditioning = [{
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "seconds_start": 0,
                "seconds_total": audio_length,
            }]

            # Generate stereo audio
            output = generate_diffusion_cond(
                model,
                steps=steps,
                cfg_scale=cfg_scale,
                conditioning=conditioning,
                sample_size=sample_size,
                sigma_min=0.3,
                sigma_max=500,
                sampler_type=sampler_type,
                seed=seed,
                device=device
            )

            # Rearrange audio batch to a single sequence
            output = rearrange(output, "b d n -> d (b n)")
            # Peak normalize, clip, convert to int16, and save to file
            output = output.to(torch.float32).div(torch.max(torch.abs(output))).clamp(-1, 1).mul(32767).to(torch.int16).cpu()
            audio_file_name = time.strftime("%Y%m%d%H%M%S", time.localtime()) + '.wav'
            audios_output_dir = os.path.join(output_dir,audio_file_name)
            if save_path:
                save_path = os.path.join(save_path, audio_file_name)
            else:
                # 默认路径在\ComfyUI\output里面
                save_path = audios_output_dir
            print("save_path："+save_path)
            
            audio = {"waveform": output.unsqueeze(0), "sample_rate": sample_rate}
            cut_audio = self.cut(audio, audio_length*1000,0.0)
            
            torchaudio.save(save_path, cut_audio[0]["waveform"].squeeze(), sample_rate)
            return (cut_audio[0],save_path)
        except Exception as e:
            raise ValueError(e)
        