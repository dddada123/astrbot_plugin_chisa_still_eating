import os
import re
import random
import shutil

__version__ = "2.3.1"

class ImageManager:
    def __init__(self, plugin_dir: str = None):
        # 💡 核心规范：所有用户的自定义图库（食物/饮品/厨师）必须走框架全局数据目录
        self.data_dir = os.path.join("data", "plugin_data", "astrbot_plugin_chisa_still_eating")
        
        # 获取插件源码自身目录
        if plugin_dir:
            self.plugin_dir = plugin_dir
        else:
            self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
            
        
        # 物理分类目录结构
        self.categories = ["food", "drink", "darkfood"]
        self.worlds = ["world1", "world2", "world3", "world4", "common"]
        self.moods = ["think", "like", "speechless", "scared"]
        
        self._ensure_infrastructure()
        
        self.cached_pools = {"food": [], "drink": [], "dark": []}
        self.cached_chefs = {}
        self.cached_memes = {}
        
    def reload_caches(self, config_global, wv_settings):
        for cat in ["food", "drink", "dark"]:
            self.cached_pools[cat] = self.scan_all_items(config_global, wv_settings, cat)
            
        self.cached_chefs.clear()
        chef_dir = os.path.join(self.data_dir, "chefs")
        if os.path.exists(chef_dir):
            for file in os.listdir(chef_dir):
                if file.startswith(".") or not file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')): continue
                parsed_chef, parsed_name = self.parse_filename(file)
                for k in [parsed_name, parsed_chef if parsed_chef else "", file.split('.')[0]]:
                    if k and k != "none":
                        if k not in self.cached_chefs: self.cached_chefs[k] = []
                        self.cached_chefs[k].append(os.path.join(chef_dir, file))
                        
        self.cached_memes.clear()
        for w in self.worlds:
            self.cached_memes[w] = {}
            for mood in self.moods:
                self.cached_memes[w][mood] = []
                t_dir = os.path.join(self.data_dir, "memes", w, mood)
                if os.path.exists(t_dir):
                    files = [f for f in os.listdir(t_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'))]
                    if files: self.cached_memes[w][mood] = [os.path.join(t_dir, f) for f in files]

    def _ensure_infrastructure(self):
        """确保所有所需目录在全局数据文件夹中已就位"""
        for cat in self.categories:
            for w in self.worlds:
                os.makedirs(os.path.join(self.data_dir, cat, w), exist_ok=True)
        # 表情包目录统一规范化
        for w in self.worlds:
            for mood in self.moods:
                os.makedirs(os.path.join(self.data_dir, "memes", w, mood), exist_ok=True)
        # 厨师图鉴专属物理目录
        os.makedirs(os.path.join(self.data_dir, "chefs"), exist_ok=True)
        

    def _process_uploads(self, config_global: dict, wv_settings: dict):
        """将 WebUI 上传的文件归档到对应物理文件夹"""
        upload_map = {
            "common": {"food": "upload_common_food", "drink": "upload_common_drink", "darkfood": "upload_common_dark"},
            "world1": {"food": "14.上传食物图片", "drink": "15.上传饮品图片", "darkfood": "16.上传黑暗料理图片"},
            "world2": {"food": "14.上传食物图片", "drink": "15.上传饮品图片", "darkfood": "16.上传黑暗料理图片"},
            "world3": {"food": "14.上传食物图片", "drink": "15.上传饮品图片", "darkfood": "16.上传黑暗料理图片"},
            "world4": {"food": "14.上传食物图片", "drink": "15.上传饮品图片", "darkfood": "16.上传黑暗料理图片"}
        }

        for w_key, maps in upload_map.items():
            for cat, key in maps.items():
                if w_key == "common":
                    uploaded = config_global.get(key, [])
                else:
                    uploaded = wv_settings.get(w_key, {}).get(key, [])
                
                if isinstance(uploaded, str):
                    uploaded = [uploaded] if uploaded else []
                    
                for file_path in uploaded:
                    if file_path and os.path.exists(file_path):
                        filename = os.path.basename(file_path)
                        target_dir = os.path.join(self.data_dir, cat, w_key)
                        target_path = os.path.join(target_dir, filename)
                        if os.path.abspath(file_path) != os.path.abspath(target_path):
                            try:
                                shutil.copy2(file_path, target_path)
                            except Exception:
                                pass

    def parse_filename(self, filename: str):
        """解析文件名，提取厨师和食物名"""
        pattern = re.compile(r"^(?:【(.*?)】)?(.*?)(?:_\d+)?\.(?:jpg|jpeg|png|gif|webp|bmp)$", re.I)
        match = pattern.match(filename)
        if match:
            return match.group(1), match.group(2).strip()
        return None, os.path.splitext(filename)[0]

    def scan_all_items(self, config_global: dict, wv_settings: dict, category: str):
        pool = []
        cat_map = {"food": ("food", "特产食物"), "drink": ("drink", "特产饮品"), "dark": ("darkfood", "黑暗料理")}
        folder_name, food_type = cat_map.get(category, ("food", "特产食物"))

        # 1. 扫描纯净的全局数据物理目录
        for w in self.worlds:
            if w != "common":
                w_conf = wv_settings.get(w, {})
                if w_conf.get("enable", True) is False:
                    continue
            target_dir = os.path.join(self.data_dir, folder_name, w)
            if not os.path.exists(target_dir): continue
            for file in os.listdir(target_dir):
                if file.startswith(".") or not file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')):
                    continue
                file_path = os.path.join(target_dir, file)
                chef, food_name = self.parse_filename(file)
                pool.append({
                    "raw_name": food_name, "food": food_name, "chef": chef or "none",
                    "wv": w, "food_type": food_type, "has_image": True, "path": file_path
                })

        # 2. 混合 WebUI 纯文字池
        for w_key, conf in wv_settings.items():
            if w_key != "common" and conf.get("enable", True) is False:
                continue
            text_key_map = {"food": "7.文字食物", "drink": "8.文字饮品", "dark": "9.文字黑暗料理"}
            t_key = text_key_map.get(category, "7.文字食物")
            for text_item in conf.get(t_key, []):
                if text_item and not any(p["food"] == text_item and p["wv"] == w_key for p in pool):
                    pool.append({
                        "raw_name": text_item, "food": text_item, "chef": "none",
                        "wv": w_key, "food_type": food_type, "has_image": False, "path": None
                    })
        return pool

    def get_chef_image(self, chef_name: str):
        if not chef_name or chef_name == "none": return None
        matched_files = []
        for k, v in self.cached_chefs.items():
            if chef_name in k or k in chef_name: matched_files.extend(v)
        if matched_files:
            gifs = [f for f in matched_files if f.lower().endswith('.gif')]
            if gifs: return random.choice(gifs)
            return random.choice(matched_files)
        return None

    def get_bot_meme(self, world_key: str, mood: str):
        files = self.cached_memes.get(world_key, {}).get(mood, [])
        if files: return random.choice(files)
        return None

    def get_egg_meme(self, char_name: str):
        """专供干饭人拦截防刷屏功能使用，读取全局数据文件夹"""
        char_dir = os.path.join(self.data_dir, "ganfanren", char_name)
        if os.path.exists(char_dir):
            files = [f for f in os.listdir(char_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'))]
            if files: return os.path.join(char_dir, random.choice(files))
        return None










