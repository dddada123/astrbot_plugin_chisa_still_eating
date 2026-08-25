import os
import asyncio          # 补充导入
from quart import jsonify, request, send_file
import threading
import requests
import zipfile
import shutil
import random
import re
import logging
import aiohttp
import hashlib
from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import EventMessageType
from .image_manager import ImageManager
from .food_data import FoodDataManager
from .rate_limiter import RateLimiter
from .responder import Responder

__version__ = "3.8.2"

@register("astrbot_plugin_chisa_still_eating", "Rua432", "3.8.2", "终极跨次元干饭系统")
class FlavorFusionUltimate(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.plugin_name = "astrbot_plugin_chisa_still_eating"
        self._register_web_api()
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.image_mgr = ImageManager(self.plugin_dir)
        self.data_mgr = FoodDataManager(config)
        self.limiter = RateLimiter()
        self.responder = Responder()
        
        self._refresh_world_cache()
        self._rebuild_alias_map()
        self._reload_all_caches()
        self._generate_help_file()
        
        self.is_downloading = False
        self.download_msg = ""
        self.downloaded_bytes = 0
        self._is_download_thread_active = False
        
        needs_download = False
        if self.config.get("force_download_assets", False):
            needs_download = True
            
        if needs_download:
            threading.Thread(target=self._download_and_extract_assets, daemon=True).start()

        eat_keywords = self.config.get("trigger_eat", ["吃什么", "吃啥", "吃点儿啥"])
        drink_keywords = self.config.get("trigger_drink", ["喝什么", "喝啥", "喝点儿啥"])
        dark_keywords = self.config.get("trigger_dark", ["来点黑暗料理"])
        common_eat_keywords = self.config.get("trigger_common_eat", ["来点现实的食物", "来点三次元食物"])
        common_drink_keywords = self.config.get("trigger_common_drink", ["来点现实的饮品", "来点三次元饮品"])
        
        if not isinstance(eat_keywords, list): eat_keywords = [eat_keywords]
        if not isinstance(drink_keywords, list): drink_keywords = [drink_keywords]
        if not isinstance(dark_keywords, list): dark_keywords = [dark_keywords]
        if not isinstance(common_eat_keywords, list): common_eat_keywords = [common_eat_keywords]
        if not isinstance(common_drink_keywords, list): common_drink_keywords = [common_drink_keywords]
        
        self.eat_pattern = re.compile("|".join([re.escape(str(k)) for k in eat_keywords if k]))
        self.drink_pattern = re.compile("|".join([re.escape(str(k)) for k in drink_keywords if k]))
        self.dark_pattern = re.compile("|".join([re.escape(str(k)) for k in dark_keywords if k]))
        self.common_eat_pattern = re.compile("|".join([re.escape(str(k)) for k in common_eat_keywords if k]))
        self.common_drink_pattern = re.compile("|".join([re.escape(str(k)) for k in common_drink_keywords if k]))

    # ================== 下载资源（修复后） ==================
    def _download_and_extract_assets(self):
        if self._is_download_thread_active:
            return
        self._is_download_thread_active = True
        self.is_downloading = True
        self.downloaded_bytes = 0
        self.download_msg = "正在从 GitHub 远程拉取基础图库资源 (约 160MB)，请耐心等待..."
        logging.info("[ChisaEating] 开始自动下载基础图库资源...")
        
        try:
            urls = [
                "https://gh-proxy.com/https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/v3.0-beta/V3.astrbot_plugin_chisa_still_eating.zip",
                "https://ghproxy.net/https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/v3.0-beta/V3.astrbot_plugin_chisa_still_eating.zip",
                "https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/v3.0-beta/V3.astrbot_plugin_chisa_still_eating.zip"
            ]
            
            zip_path = os.path.join(self.image_mgr.data_dir, "assets_temp.zip")
            os.makedirs(self.image_mgr.data_dir, exist_ok=True)
            
            TARGET_HASH = "239dda1a6de8ad4227f166eabe19db83c9ce4a15806e14fdbd7ecbbf98da30ae"
            success = False
            
            for url in urls:
                try:
                    logging.info(f"[ChisaEating] 尝试从 {url} 下载...")
                    self.downloaded_bytes = 0
                    response = requests.get(url, stream=True, timeout=120)
                    response.raise_for_status()
                    
                    sha256_hash = hashlib.sha256()
                    with open(zip_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                sha256_hash.update(chunk)
                                self.downloaded_bytes += len(chunk)
                                
                    downloaded_hash = sha256_hash.hexdigest()
                    if downloaded_hash != TARGET_HASH:
                        logging.warning(
                            f"[ChisaEating] 安全告警：下载的资源包哈希值不匹配！\n"
                            f"预期: {TARGET_HASH}\n"
                            f"实际: {downloaded_hash}\n"
                            "已自动删除危险文件，尝试下一个节点..."
                        )
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                        continue
                        
                    success = True
                    break
                except Exception as e:
                    logging.warning(f"[ChisaEating] 下载节点失败 ({url}): {e}")
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                        
            if success:
                self.download_msg = "图库下载完成并经过 SHA-256 安全校验，正在解压部署..."
                logging.info("[ChisaEating] 下载完成且完整性校验通过，开始解压...")
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        extract_tmp = os.path.join(self.image_mgr.data_dir, "extract_tmp")
                        zip_ref.extractall(extract_tmp)
                        
                        src_dir = extract_tmp
                        for root, dirs, files in os.walk(extract_tmp):
                            if "food" in dirs or "drink" in dirs or "chefs" in dirs:
                                src_dir = root
                                break
                        
                        for item in os.listdir(src_dir):
                            s = os.path.join(src_dir, item)
                            d = os.path.join(self.image_mgr.data_dir, item)
                            if os.path.isdir(s):
                                if os.path.exists(d):
                                    shutil.rmtree(d)
                                shutil.copytree(s, d)
                            else:
                                shutil.copy2(s, d)
                                
                    logging.info("[ChisaEating] 基础图库解压部署完成！")
                    self._reload_all_caches()
                except Exception as e:
                    logging.error(f"[ChisaEating] 解压失败: {e}")
                finally:
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    extract_tmp = os.path.join(self.image_mgr.data_dir, "extract_tmp")
                    if os.path.exists(extract_tmp):
                        shutil.rmtree(extract_tmp, ignore_errors=True)
            else:
                logging.error("[ChisaEating] 基础图库所有下载节点均超时或哈希校验失败！请前往后台取消勾选强制下载，并根据 Readme 手动下载安装。")
            
            if self.config.get("force_download_assets", False):
                self.config["force_download_assets"] = False
                
        finally:
            self.is_downloading = False
            self.downloaded_bytes = 0
            self._is_download_thread_active = False

    # ================== 辅助函数（原样保留） ==================
    def _reload_all_caches(self):
        self.image_mgr.reload_caches(self.config, self.wv_settings)
        self.cached_ganfanren = self._get_ganfanren_data()

    def _get_ganfanren_data(self):
        ganfanren_pool = {}
        user_dir = os.path.join(self.image_mgr.data_dir, "ganfanren")
        os.makedirs(user_dir, exist_ok=True)

        for scan_dir in [user_dir]:
            if not os.path.exists(scan_dir): 
                continue
            for folder_name in os.listdir(scan_dir):
                folder_path = os.path.join(scan_dir, folder_name)
                if not os.path.isdir(folder_path): 
                    continue

                if folder_name not in ganfanren_pool:
                    ganfanren_pool[folder_name] = {"images": [], "words": []}

                for file_name in os.listdir(folder_path):
                    file_path = os.path.join(folder_path, file_name)
                    if file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                        ganfanren_pool[folder_name]["images"].append(file_path)
                    # 修复：恢复读取 words.txt
                    elif file_name.lower() == 'words.txt':
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                lines = f.readlines()
                        except UnicodeDecodeError:
                            try:
                                with open(file_path, 'r', encoding='gbk') as f:
                                    lines = f.readlines()
                            except Exception:
                                continue
                        clean_lines = [line.strip() for line in lines if line.strip()]
                        ganfanren_pool[folder_name]["words"].extend(clean_lines)

        empty_keys = [k for k, v in ganfanren_pool.items() if not v["images"]]
        for k in empty_keys: 
            del ganfanren_pool[k]

        return ganfanren_pool

    def _generate_help_file(self):
        pool = getattr(self, "cached_ganfanren", {})
        names = list(pool.keys())
        help_path = os.path.join(self.image_mgr.data_dir, "👉当前可用干饭人一览.txt")
        
        os.makedirs(os.path.dirname(help_path), exist_ok=True)
        with open(help_path, "w", encoding="utf-8") as f:
            f.write("【系统扫描报告 - ChisaEating v3.7.2】\n")
            f.write("当前已识别到以下干饭人：\n")
            for name in names:
                f.write(f"- {name}\n")
            f.write("\n如需在 WebUI 指定卡池，请直接复制下方文本到【指定干饭人卡池】配置框：\n")
            f.write(";".join(names) + "\n")
        logging.info(f"[ChisaEating v3.8.2] 📋 已更新可用干饭人清单到 plugin_data 目录，共 {len(names)} 名")

    def _refresh_world_cache(self):
        raw_settings = {
            "world1": self.config.get("world1", {}),
            "world2": self.config.get("world2", {}),
            "world3": self.config.get("world3", {}),
            "world4": self.config.get("world4", {})
        }
        self.wv_settings = {}
        for wk, v in raw_settings.items():
            if isinstance(v, dict) and "default" in v:
                self.wv_settings[wk] = v["default"]
            else:
                self.wv_settings[wk] = v

    def _rebuild_alias_map(self):
        self.alias_map = {}
        for i in range(1, 5):
            w_key = f"world{i}"
            aliases = self.config.get(f"{w_key}_aliases", [])
            inner_conf = self.wv_settings.get(w_key, {})
            inner_aliases = inner_conf.get("2.世界别称", [])
            
            combined = set([str(a).strip() for a in (aliases + inner_aliases) if a])
            for alias in combined:
                self.alias_map[alias] = w_key

    def _resolve_active_key(self) -> str:
        selection = self.config.get("active_world", "世界1(鸣潮)")
        if "世界1" in selection: return "world1"
        if "世界2" in selection: return "world2"
        if "世界3" in selection: return "world3"
        if "世界4" in selection: return "world4"
        return "world1"

    # ================== 消息拦截器（修复装饰器） ==================
    @staticmethod
    async def _make_gif_copy(path: str) -> str:
        """后台内存转换：将静态图瞬间压成 GIF，借此欺骗 QQ 渲染为小表情气泡"""
        if not path or not os.path.exists(path):
            return path
        if path.lower().endswith(".gif"):
            return path
            
        import tempfile, random
        temp_path = os.path.join(tempfile.gettempdir(), f"chisa_meme_{os.getpid()}_{random.randint(100000, 999999)}.gif")
        try:
            from PIL import Image
            def _convert():
                with Image.open(path) as img:
                    if img.mode not in ('RGB', 'RGBA', 'P'):
                        img = img.convert('RGBA')
                    img.save(temp_path, format="GIF")
            await asyncio.get_event_loop().run_in_executor(None, _convert)
            return temp_path
        except Exception as e:
            logging.warning(f"[ChisaEating] 表情包降维GIF转换失败: {e}")
            return path

    async def _apply_meme_image(self, chain_obj, meme_path: str):
        """定向发送配菜（导游/干饭人/厨师），不碰主菜"""
        if not meme_path:
            return
        if self.config.get("convert_meme_to_gif", True):
            gif_path = await self._make_gif_copy(meme_path)
            chain_obj.file_image(gif_path)
        else:
            chain_obj.file_image(meme_path)

    # 修复：将事件装饰器放在此方法上

    async def page_update_ganfanren(self):
        try:
            import os
            import json
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            name = payload.get("name", "").strip()
            words = payload.get("words", "").strip()
            if not name: return jsonify({"status":"error"}), 400
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            try: base_data_path = get_astrbot_data_path()
            except: base_data_path = "data"
            gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren", name))
            if os.path.exists(gf_dir):
                with open(os.path.join(gf_dir, "words.txt"), "w", encoding="utf-8") as f:
                    f.write(words)
                self._reload_all_caches()
                return jsonify({"status":"ok"}), 200
            return jsonify({"status":"error", "message":"Not found"}), 404
        except Exception as e:
            from quart import jsonify
            return jsonify({"status":"error", "message":str(e)}), 500

    
    async def page_delete_ganfanren(self):
        """WebUI: 彻底删除干饭人及其所有数据"""
        try:
            import os
            import shutil
            from quart import jsonify, request
            payload = await request.get_json(silent=True)
            if not payload:
                raw_data = await request.get_data(as_text=True)
                import json
                try: payload = json.loads(raw_data)
                except: payload = {}
                
            name = payload.get("name", "").strip()
            if not name:
                return jsonify({"status": "error", "message": "名字不能为空"}), 400
                
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren", name))
            if os.path.exists(gf_dir) and os.path.isdir(gf_dir):
                shutil.rmtree(gf_dir)
                return jsonify({"status": "ok", "message": f"已成功删除干饭人 {name}"})
            else:
                return jsonify({"status": "error", "message": "该干饭人不存在"}), 404
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    
    async def page_rename_image(self):
        """WebUI: 重命名本地图片"""
        try:
            import os
            from quart import jsonify, request
            payload = await request.get_json(silent=True)
            if not payload:
                raw_data = await request.get_data(as_text=True)
                import json
                try: payload = json.loads(raw_data)
                except: payload = {}
                
            old_path = payload.get("old_path", "").strip()
            new_name = payload.get("new_name", "").strip()
            new_ext = payload.get("new_ext", "").strip()

            if not old_path or not new_name:
                return jsonify({"status": "error", "message": "参数缺失"}), 400

            if new_ext and not new_ext.startswith("."): 
                new_ext = "." + new_ext

            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            try: base_data_path = get_astrbot_data_path()
            except: base_data_path = "data"
            base_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))

            full_old_path = os.path.abspath(os.path.join(base_dir, old_path))
            if not full_old_path.startswith(base_dir) or not os.path.exists(full_old_path):
                return jsonify({"status": "error", "message": "原文件不存在或无权限"}), 404

            parent_dir = os.path.dirname(full_old_path)
            final_name = new_name + new_ext
            full_new_path = os.path.abspath(os.path.join(parent_dir, final_name))

            if not full_new_path.startswith(base_dir):
                return jsonify({"status": "error", "message": "非法的新文件名"}), 400

            if full_new_path != full_old_path:
                counter = 1
                base_new_name = new_name
                while os.path.exists(full_new_path):
                    final_name = f"{base_new_name}_{counter}{new_ext}"
                    full_new_path = os.path.abspath(os.path.join(parent_dir, final_name))
                    counter += 1
                os.rename(full_old_path, full_new_path)

            self._reload_all_caches()
            return jsonify({"status": "ok", "message": "重命名成功"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_delete_image(self):
        try:
            import os
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            
            paths = payload.get("paths", [])
            # Fallback single path to array
            if "path" in payload and payload["path"] not in paths:
                paths.append(payload["path"])
                
            if not paths:
                return jsonify({"status":"error", "message": "No path provided"}), 400
                
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            try: base_data_path = get_astrbot_data_path()
            except: base_data_path = "data"
            base_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            
            deleted = 0
            for path in paths:
                if ".." in path: continue
                full_path = os.path.abspath(os.path.join(base_dir, path))
                if not full_path.startswith(base_dir): continue
                
                if os.path.exists(full_path) and os.path.isfile(full_path):
                    os.remove(full_path)
                    deleted += 1
                    
            if deleted > 0:
                self._reload_all_caches()
                return jsonify({"status":"ok", "message": f"成功删除 {deleted} 张图片"}), 200
            return jsonify({"status":"error", "message": "File not found"}), 404
        except Exception as e:
            from quart import jsonify
            return jsonify({"status":"error", "message": str(e)}), 500

    async def page_upload_image(self):
        try:
            import os
            import base64
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            category = payload.get("category")
            world = payload.get("world", "")
            mode = payload.get("mode", "batch")
            single_chef = payload.get("single_chef", "").strip()
            single_dish = payload.get("single_dish", "").strip()
            mood = payload.get("mood", "think")
            files = payload.get("files", [])
            
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            try: base_data_path = get_astrbot_data_path()
            except: base_data_path = "data"
            base_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            
            if category in ["food", "drink", "darkfood"]:
                if not world: world = "common"
                target_dir = os.path.join(base_dir, category, world)
            elif category == "chefs":
                target_dir = os.path.join(base_dir, "chefs")
            elif category == "memes":
                if not world: world = "common"
                target_dir = os.path.join(base_dir, "memes", world, mood)
            elif category == "ganfanren":
                target_dir = os.path.join(base_dir, "ganfanren", payload.get("char_name"))
            else:
                return jsonify({"status":"error", "message": "Invalid category"}), 400
                
            os.makedirs(target_dir, exist_ok=True)
            
            for f in files:
                fname = f.get("filename")
                b64 = f.get("data", "")
                if not fname or not b64: continue
                
                ext = os.path.splitext(fname)[1]
                if mode == "single" and category in ["food", "drink", "darkfood", "chefs"]:
                    if category == "chefs":
                        base_name = f"{single_dish}"
                    else:
                        base_name = f"【{single_chef}】{single_dish}" if single_chef else single_dish
                        
                    final_name = base_name + ext
                    counter = 1
                    while os.path.exists(os.path.join(target_dir, final_name)):
                        final_name = f"{base_name}_{counter}{ext}"
                        counter += 1
                    fname = final_name
                    
                if b64.startswith("data:"): b64 = b64.split(",")[1]
                img_path = os.path.join(target_dir, fname)
                with open(img_path, "wb") as imgf:
                    imgf.write(base64.b64decode(b64))
                    
            self._reload_all_caches()
            return jsonify({"status":"ok"}), 200
        except Exception as e:
            import traceback
            import logging
            logging.error(f"[ChisaEating] upload error: {traceback.format_exc()}")
            from quart import jsonify
            return jsonify({"status":"error", "message": str(e)}), 500

    @filter.event_message_type(EventMessageType.ALL)
    async def global_message_interceptor(self, event: AstrMessageEvent, *args, **kwargs):
        msg_text = event.message_str
        if not msg_text: return
        msg_text = msg_text.strip()
        
        is_plugin_cmd = False
        if ("/加菜" in msg_text or "加菜" in msg_text or "/上传厨师" in msg_text or "上传厨师" in msg_text or 
            "帮助" in msg_text or "吃什么" in msg_text or "喝什么" in msg_text or "特产" in msg_text or 
            "特饮" in msg_text or "吃饭" in msg_text or "料理" in msg_text or "召唤" in msg_text or "特供" in msg_text) and "千小妹图库下载进度" not in msg_text:
            is_plugin_cmd = True
            
        if self.is_downloading and is_plugin_cmd:
            mb = self.downloaded_bytes / (1024 * 1024)
            progress_msg = f"【千小妹下载进度】\n正在为您搬运跨次元美食资源...下载完成后即可正常使用以及查看帮助\n当前已下载: {mb:.2f} MB / 160.46 MB"
            yield event.make_result().message(progress_msg)
            event.stop_event()
            return

        if "/加菜 " in msg_text or "加菜 " in msg_text:
            async for res in self.handle_add_food(event, msg_text):
                yield res
            event.stop_event()
            return
        if "/上传厨师" in msg_text or "上传厨师" in msg_text:
            async for res in self.handle_upload_chef(event, msg_text):
                yield res
            event.stop_event()
            return
            
        if msg_text == "/千小妹图库下载进度" or msg_text == "千小妹图库下载进度":
            if self.is_downloading:
                mb = self.downloaded_bytes / (1024 * 1024)
                yield event.make_result().message(f"【千小妹下载进度】\n正在为您搬运跨次元美食资源...下载完成后即可正常使用以及查看帮助\n当前已下载: {mb:.2f} MB / 160.46 MB")
            else:
                yield event.make_result().message("【千小妹提示】当前没有正在进行的图库下载任务哦。")
            event.stop_event()
            return

        if "/更新千小妹图库" in msg_text or "更新千小妹图库" in msg_text:
            uid = str(event.get_sender_id())
            admin_users = [str(x).strip() for x in self.config.get("admin_users", []) if str(x).strip()]
            if not admin_users or uid not in admin_users:
                yield event.make_result().message("【权限不足】只有管理员才能执行图库更新指令哦！")
            else:
                if self.is_downloading:
                    yield event.make_result().message("【千小妹提示】图库正在下载中，请勿重复触发...")
                else:
                    threading.Thread(target=self._download_and_extract_assets, daemon=True).start()
                    yield event.make_result().message("【千小妹提示】已收到显式确认！开始从 Github 拉取并更新图库 (约160MB)，请查看后台日志或稍后重试抽卡。回复/千小妹图库下载进度或任意吃什么命令可查看当前下载进度。")
            event.stop_event()
            return
            
        msg_obj = event.message_obj
        group_id = None
        if msg_obj and hasattr(msg_obj, 'group_id'):
            group_id = str(msg_obj.group_id).strip() if msg_obj.group_id else None
        
        if group_id:
            if self.config.get("enable_blacklist", False):
                blacklist = [str(x).strip() for x in self.config.get("blacklist_groups", []) if str(x).strip()]
                if group_id in blacklist:
                    return
            if self.config.get("enable_whitelist", False):
                whitelist = [str(x).strip() for x in self.config.get("whitelist_groups", []) if str(x).strip()]
                if group_id not in whitelist:
                    return
        
        if msg_text in ["千小妹还在吃帮助", "千咲吃什么帮助", "干饭帮助", "美食帮助", "千小妹帮助", "千小妹吃什么帮助"]:
            help_text = """🌸 【千小妹跨次元干饭指南 v3.8.2】 🌸
不知道今天吃啥？让异次元的导游们为你随机摇号吧！

🎲 基础盲盒（全宇宙随机）
💬 吃什么 / 吃啥：全宇宙卡池随机抽选一道美食。
💬 喝什么 / 喝啥：全宇宙卡池随机抽选一杯饮品。

🌍 定向打卡（想吃特定世界的？）
💬 来点现实的食物 / 来点现实的饮品：只想吃地球上的普通外卖？用这个！
💬 [别名]特产 / [别名]特饮：精准锁定某个世界的菜单（例如：鸣潮特产、原神特饮）。

👑 羁绊召唤（吃老婆/老公做的饭）
💬 召唤[厨师名]下厨 / [厨师名]特供料理：强行过滤奖池，只吃TA亲手做的菜，附赠专属立绘展示！（例如：召唤爱弥斯下厨、弗洛洛特供料理）。

☠️ 娱乐整活
💬 来点黑暗料理：导游的恶作剧，吃出人命概不负责！
💡 提示：频繁点菜不仅会被导游吐槽，饭还可能会被别的干饭人“截胡”抢走哦！
---
⚙️ 系统与图库管理 (注：需在AstrBot后台配置管理员)
💬 千小妹图库下载进度：随时查看后台图库的拉取进度。
💬 更新千小妹图库：强制进行160MB图包的安全拉取。
💬 【加菜格式】：加菜 [世界] [分类] [菜名]
⚠️ (参数之间必须打空格，且图片要和文字发在同一条消息里！)
💡 举例：加菜 三次元 食物 肯德基肉霸堡 (带图)
💬 【加大厨格式】：上传厨师 [厨师名]
💡 举例：上传厨师 刻晴 (带图)
⚠️ 若您是在服务器后台手动放入新图片或TXT，请务必在WebUI点击【重载插件】或群内发送 更新千小妹图库 刷新缓存。

(📝 注：以上所有指令均不受机器人名字影响。发“小爱吃什么”也能完美触发哦！)"""
            yield event.make_result().message(help_text)
            event.stop_event()
            return

        self._refresh_world_cache()
        self._rebuild_alias_map() 
        
        category = None
        forced_world = None

        if self.dark_pattern.search(msg_text): 
            category = "dark"
        elif self.common_eat_pattern.search(msg_text):
            category = "food"
            forced_world = "common"
        elif self.common_drink_pattern.search(msg_text):
            category = "drink"
            forced_world = "common"
        elif self.drink_pattern.search(msg_text): 
            category = "drink"
        elif self.eat_pattern.search(msg_text): 
            category = "food"

        forced_chef = None
        chef_match = re.search(r"想和(.+?)吃饭|(.+?)特供料理|召唤(.+?)下厨", msg_text)
        if chef_match:
            extracted = next((g for g in chef_match.groups() if g), None)
            if extracted and extracted != "黑暗":
                forced_chef = extracted.strip()
                if not category:
                    category = "food"

        if not forced_world:
            for alias, w_key in self.alias_map.items():
                if category and alias in msg_text:
                    forced_world = w_key
                    break
                if not category and (f"{alias}特产" in msg_text or f"{alias}吃" in msg_text):
                    category = "food"
                    forced_world = w_key
                    break
                if not category and (f"{alias}特饮" in msg_text or f"{alias}喝" in msg_text):
                    category = "drink"
                    forced_world = w_key
                    break

        if not category:
            return 
            
        async for res in self.execute_flow(event, category, forced_world, forced_chef):
            yield res

    # ================== 核心流程 ==================
    async def execute_flow(self, event: AstrMessageEvent, category: str, forced_world: str = None, forced_chef: str = None):
        event.should_call_llm(True)
        uid = event.get_sender_id()
        msg_obj = event.message_obj
        group_id = str(msg_obj.group_id) if msg_obj and hasattr(msg_obj, 'group_id') and msg_obj.group_id else str(uid)
        
        if forced_world and forced_world != "common":
            active_key = forced_world
        else:
            active_key = self._resolve_active_key()
            
        active_conf = self.wv_settings.get(active_key, {})
            
        bot_pool = active_conf.get("3.自称池", [])
        bot_host = random.choice(bot_pool if bot_pool else ["推荐官"])
        
        world_host = active_conf.get("1.世界名称", "") or f"世界{active_key[-1]}"
        world_a_aliases = [a for a in active_conf.get("2.世界别称", []) if a]
        if world_a_aliases:
            world_host = random.choice([world_host] + world_a_aliases)

        if self.limiter.is_spaming(uid, self.config.get("spam_threshold", 3)):
            if random.randint(1, 100) <= self.config.get("interception_egg_chance", 50):
                ganfanren_pool = getattr(self, "cached_ganfanren", {})
                if ganfanren_pool:
                    valid_names = list(ganfanren_pool.keys())
                    egg_role = "千咲" if "千咲" in valid_names else random.choice(valid_names)
                    inter_text = f"【拦截警报】你点得太快啦！{egg_role}怕你撑着，已经先你一步把厨房吃空了！"
                    meme_file = self.image_mgr.get_egg_meme(egg_role)
                else:
                    inter_text = "【拦截警报】你点得太快啦！系统已开启防刷屏管制！"
                    meme_file = None
            else:
                inter_pool = active_conf.get("6.打断句式", [])
                inter_text = random.choice(inter_pool if inter_pool else [f"{bot_host}觉得你点得太频繁了。"]).format(bot=bot_host)
                meme_file = self.image_mgr.get_bot_meme(active_key, "speechless")
                
            chain = event.make_result().message(inter_text)
            await self._apply_meme_image(chain, meme_file)
            yield chain
            event.stop_event()
            return

        is_generic_query = not forced_world and not forced_chef and category != "dark"
        cd_seconds = self.config.get("repeat_cooldown", 60)
        if is_generic_query and not self.limiter.is_repeat_in_cooldown(group_id, cd_seconds) and (random.randint(1, 100) <= self.config.get("repeat_prob", 10)):
            self.limiter.record_repeat_trigger(group_id)
            if category == "food":
                fallback_pool = self.config.get("eat_fallback_words", ["是啊，吃什么"])
            else:
                fallback_pool = self.config.get("drink_fallback_words", ["是啊，喝什么"])
            text = random.choice(fallback_pool if fallback_pool else ["是啊，吃/喝什么"]).format(bot=bot_host)
            chain = event.make_result().message(text)
            meme_file = self.image_mgr.get_bot_meme(active_key, "think")
            await self._apply_meme_image(chain, meme_file)
            yield chain
            event.stop_event()
            return

        food_dir = os.path.join(self.image_mgr.data_dir, "food")
        if not os.path.exists(food_dir) or not os.listdir(food_dir):
            yield event.make_result().message("""【千小妹系统提示】检测到基础图库为空！
为了符合安全规范，需要BOT管理员手动确认基础资源包的拉取。

🛠️ 【全自动拉取方案】：
请先前往 AstrBot 后台 WebUI，在本插件配置的『管理员账号白名单』中填入您的 QQ 号。
随后在群内发送 /更新千小妹图库 即可触发 160MB 图包的安全拉取。

📦 【网盘手动兜底方案】（若拉取超时/失败）：
夸克：https://pan.quark.cn/s/301110d45a48
百度：https://pan.baidu.com/s/1ZHfYz8vNL5JU0jyFtHiYqQ?pwd=erm9
（将解压出的food等文件夹放入 data/plugin_data/astrbot_plugin_chisa_still_eating 中即可）""")
            event.stop_event()
            return
            
        pool = self.image_mgr.cached_pools.get(category, [])
        
        if not pool:
            yield event.make_result().message("""【千小妹系统提示】检测到基础图库为空！
为了符合安全规范，需要BOT管理员手动确认基础资源包的拉取。

🛠️ 【全自动拉取方案】：
请先前往 AstrBot 后台 WebUI，在本插件配置的『管理员账号白名单』中填入您的 QQ 号。
随后在群内发送 /更新千小妹图库 即可触发 160MB 图包的安全拉取。

📦 【网盘手动兜底方案】（若拉取超时/失败）：
夸克：https://pan.quark.cn/s/301110d45a48
百度：https://pan.baidu.com/s/1ZHfYz8vNL5JU0jyFtHiYqQ?pwd=erm9
（将解压出的food等文件夹放入 data/plugin_data/astrbot_plugin_chisa_still_eating 中即可）""")
            event.stop_event()
            return
            
        common_texts = []
        if category == "food":
            common_texts = self.config.get("common_food_text", [])
        elif category == "drink":
            common_texts = self.config.get("common_drink_text", [])
            
        for text_item in common_texts:
            item_name = str(text_item).strip()
            if item_name:
                pool.append({
                    "wv": "common", 
                    "food": item_name, 
                    "raw_name": item_name,
                    "chef": "none", 
                    "has_image": False,
                    "path": None
                })
        
        if forced_world:
            strict_pool = [item for item in pool if item["wv"] == forced_world]
            if strict_pool:
                pool = strict_pool
                
        if forced_chef:
            chef_pool = [item for item in pool if item.get("chef") == forced_chef]
            if not chef_pool:
                if category == "food":
                    drink_pool = self.image_mgr.cached_pools.get("drink", [])
                    chef_pool = [item for item in drink_pool if item.get("chef") == forced_chef]
            
            if not chef_pool:
                yield event.make_result().message(f"【厨师下班】{forced_chef}今天不在厨房哦～（图库中未找到该厨师的作品）")
                event.stop_event()
                return
            pool = chef_pool

        picked = self.data_mgr.filter_and_pick(group_id, pool, active_key)
        
        if not picked:
            yield event.make_result().message("【卡池告急】未找到任何可用的食物/饮品数据！请检查文件夹或配置。")
            event.stop_event()
            return

        food_name = picked["food"]
        chef_name = picked["chef"]
        origin_key = picked["wv"]
        
        if chef_name != "none":
            full_food_desc = f"由【{chef_name}】特制的{food_name}"
        else:
            full_food_desc = food_name

        final_text = ""
        mood = "like"
        use_ai = False

        if self.config.get("enable_ai", False) and random.randint(1, 100) <= self.config.get("ai_probability", 5):
            is_crossover = (origin_key != "common" and origin_key != active_key)
            ai_text = await self.responder.generate_response(
                self.context, event, bot_host, world_host, food_name, category, chef_name, is_crossover
            )
            if ai_text:
                final_text = ai_text
                use_ai = True
                mood = "scared" if category == "dark" else "like"

        if not use_ai:
            fmt_args = {
                "bot": bot_host, "bot_a": bot_host, "food": food_name, 
                "chef": chef_name, "full_food_desc": full_food_desc,
                "world_a": world_host
            }
            is_crossover = (origin_key != "common" and origin_key != active_key)
            is_drink = (category == "drink")
            
            if category == "dark":
                pool_text = self.config.get("dark_drink_templates" if is_drink else "dark_templates", [])
                if not pool_text: pool_text = self.config.get("dark_templates", [])
                final_text = random.choice(pool_text if pool_text else ["危险的{full_food_desc}！"]).format(**fmt_args)
                mood = "scared"
            elif is_crossover:
                cross_conf = self.wv_settings.get(origin_key, {})
                world_b_host = cross_conf.get("1.世界名称", "") or "异世界"
                world_b_aliases = [a for a in cross_conf.get("2.世界别称", []) if a]
                if world_b_aliases:
                    world_b_host = random.choice([world_b_host] + world_b_aliases)
                fmt_args["world_b"] = world_b_host
                
                bot_b_pool = cross_conf.get("3.自称池", ["异界人"])
                fmt_args["bot_b"] = random.choice(bot_b_pool if bot_b_pool else ["异界人"])

                pool_text = self.config.get("crossover_drink_templates" if is_drink else "crossover_templates", [])
                if not pool_text: pool_text = self.config.get("crossover_templates", [])
                final_text = random.choice(pool_text if pool_text else ["{bot_a}遇到了{bot_b}，一起吃了{full_food_desc}"]).format(**fmt_args)
            elif chef_name != "none":
                pool_key = "12.厨师饮品句式" if is_drink else "5.厨师句式"
                pool_text = active_conf.get(pool_key, [])
                if not pool_text: pool_text = active_conf.get("5.厨师句式", [])
                final_text = random.choice(pool_text if pool_text else ["【{chef}】特制了{food}"]).format(**fmt_args)
            elif origin_key == "common":
                pool_key = "generic_drink_templates" if is_drink else "generic_templates"
                pool_text = self.config.get(pool_key, [])
                if not pool_text: pool_text = self.config.get("generic_templates", [])
                final_text = random.choice(pool_text if pool_text else ["铛铛！为你抽中了美味的{food}！"]).format(**fmt_args)
            else:
                pool_key = "11.专属饮品句式" if is_drink else "4.专属句式"
                pool_text = active_conf.get(pool_key, [])
                if not pool_text: pool_text = active_conf.get("4.专属句式", [])
                generic_pool = self.config.get("generic_drink_templates" if is_drink else "generic_templates", [])
                if not generic_pool: generic_pool = self.config.get("generic_templates", [])
                combined_pool = pool_text + generic_pool
                final_text = random.choice(combined_pool if combined_pool else ["推荐{food}"]).format(**fmt_args)
                
            if any(word in food_name for word in ["冰", "冷", "冻", "雪糕"]):
                final_text = final_text.replace("热腾腾的", "冰凉的").replace("趁热吃吧", "趁凉吃吧")

        img_to_send = picked.get("path") if picked.get("has_image") else None
        meme_to_send = None
        
        if random.randint(1, 100) <= self.config.get("egg_prob", 10):
            ganfanren_pool = getattr(self, "cached_ganfanren", {})
            if ganfanren_pool:
                pool_config = self.config.get("egg_pool", "")
                allowed_pool = None
                if pool_config and pool_config.strip().lower() != "random":
                    cleaned_config = pool_config.replace("；", ";")
                    allowed_pool = [name.strip() for name in cleaned_config.split(";") if name.strip()]
                
                valid_names = list(ganfanren_pool.keys())
                if allowed_pool:
                    valid_names = [name for name in allowed_pool if name in valid_names]
                if not valid_names:
                    valid_names = list(ganfanren_pool.keys())
                
                lucky_name = random.choice(valid_names)
                meme_to_send = random.choice(ganfanren_pool[lucky_name]["images"])
                
                words_list = ganfanren_pool[lucky_name]["words"]
                if words_list:
                    word = random.choice(words_list)
                else:
                    word = "但是所有食物被一个神秘吃货一扫而空！"
                
                final_text += f"\n\n{word}"
            else:
                final_text += "\n\n但是所有食物被一个神秘吃货一扫而空！"
        else:
            if chef_name != "none" and random.randint(1, 100) <= self.config.get("chef_meme_prob", 50):
                meme_to_send = self.image_mgr.get_chef_image(chef_name)
            elif random.randint(1, 100) <= self.config.get("global_meme_prob", 30):
                meme_to_send = self.image_mgr.get_bot_meme(active_key, mood)

        result = event.make_result().message(final_text)
        if img_to_send: result.file_image(img_to_send)
        await self._apply_meme_image(result, meme_to_send)
            
        yield result
        event.stop_event()

    # ================== 加菜功能 ==================
    async def handle_add_food(self, event, msg_text: str):
        uid = str(event.get_sender_id())
        admin_users = [str(x).strip() for x in self.config.get("admin_users", []) if str(x).strip()]
        
        if not admin_users:
            yield event.make_result().message("【加菜失败】未配置管理员！请前往 WebUI 的本插件配置中填写「管理员账号白名单」。")
            return
            
        if uid not in admin_users:
            yield event.make_result().message("【越权警告】只有厨师长（管理员）可以加菜哦！")
            return

        idx = msg_text.find("加菜 ")
        if idx != -1:
            pure_args = msg_text[idx + 3:].strip()
        else:
            pure_args = ""

        text_parts = pure_args.split(maxsplit=2)
        if len(text_parts) < 3:
            yield event.make_result().message("""指令格式错误！
正确格式：加菜 [世界] [分类] [菜名]
示例：加菜 鸣潮 饮品 冰吸生椰拿铁 (请连带图片一起发送)""")
            return

        world_input = text_parts[0]
        cat_input = text_parts[1]
        food_name_input = text_parts[2]

        target_world = None
        if world_input in ["三次元", "现实", "common"]:
            target_world = "common"
        else:
            self._refresh_world_cache()
            self._rebuild_alias_map()
            for alias, w_key in self.alias_map.items():
                if world_input == alias or world_input == w_key:
                    target_world = w_key
                    break
        
        if not target_world:
            yield event.make_result().message(f"加菜失败：未识别的世界 '{world_input}'。")
            return
            
        cat_map = {"食物": "food", "饮品": "drink", "黑暗料理": "darkfood"}
        target_cat = cat_map.get(cat_input)
        if not target_cat:
            yield event.make_result().message(f"加菜失败：未识别的分类 '{cat_input}'，只能是 食物、饮品 或 黑暗料理。")
            return

        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            food_name_input = food_name_input.replace(char, "")
        food_name_input = food_name_input.strip()
        
        if not food_name_input:
            yield event.make_result().message("加菜失败：菜名不合法！")
            return

        from astrbot.api.message_components import Image
        images = [comp for comp in event.message_obj.message if isinstance(comp, Image)]
        
        if not images:
            yield event.make_result().message("加菜失败：没有检测到图片，请将图片和指令在同一条消息中发出。")
            return

        target_dir = os.path.join(self.image_mgr.data_dir, target_cat, target_world)
        os.makedirs(target_dir, exist_ok=True)
        
        saved_count = 0
        
        async with aiohttp.ClientSession() as session:
            for img in images:
                content = None
                ext = ".jpg"
                if hasattr(img, 'url') and img.url and img.url.startswith('http'):
                    try:
                        async with session.get(img.url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                if "png" in img.url.lower(): ext = ".png"
                                elif "gif" in img.url.lower(): ext = ".gif"
                    except Exception as e:
                        logging.error(f"Download error: {e}")
                elif hasattr(img, 'file') and img.file and os.path.exists(img.file):
                    try:
                        with open(img.file, 'rb') as f:
                            content = f.read()
                        if img.file.lower().endswith('.png'): ext = ".png"
                        elif img.file.lower().endswith('.gif'): ext = ".gif"
                    except Exception:
                        pass
                
                if not content:
                    continue
                    
                save_path = os.path.join(target_dir, f"{food_name_input}{ext}")
                if os.path.exists(save_path):
                    counter = 1
                    while True:
                        save_path = os.path.join(target_dir, f"{food_name_input}_{counter}{ext}")
                        if not os.path.exists(save_path):
                            break
                        counter += 1
                        
                try:
                    with open(save_path, "wb") as f:
                        f.write(content)
                    saved_count += 1
                except Exception as e:
                    logging.error(f"Save error: {e}")
                    
        if saved_count > 0:
            self._reload_all_caches()
            yield event.make_result().message(f"✅ 加菜成功！\n共收录 {saved_count} 张【{food_name_input}】至 {world_input} 的 {cat_input} 库中！")
        else:
            yield event.make_result().message("加菜失败：图片下载失败或平台限制导致无法读取。")
        return

    # ================== 上传厨师 ==================
    async def handle_upload_chef(self, event, msg_text: str):
        uid = str(event.get_sender_id())
        admin_users = [str(x).strip() for x in self.config.get("admin_users", []) if str(x).strip()]
        
        if not admin_users:
            yield event.make_result().message("【上传厨师失败】未配置管理员！请前往 WebUI 的本插件配置中填写「管理员账号白名单」。")
            return
            
        if uid not in admin_users:
            yield event.make_result().message("【越权警告】只有厨师长（管理员）可以上传厨师哦！")
            return

        idx = msg_text.find("上传厨师")
        if idx != -1:
            pure_args = msg_text[idx + 4:].strip()
        else:
            pure_args = ""

        chef_name = pure_args

        if not chef_name:
            yield event.make_result().message("""指令格式错误！
正确格式：上传厨师 [厨师名]
示例：上传厨师 奥黛塔 (请连带图片一起发送)""")
            return

        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            chef_name = chef_name.replace(char, "")
        chef_name = chef_name.strip()
        
        if not chef_name:
            yield event.make_result().message("上传失败：厨师名不合法！")
            return

        from astrbot.api.message_components import Image
        images = [comp for comp in event.message_obj.message if isinstance(comp, Image)]
        
        if not images:
            yield event.make_result().message("上传失败：没有检测到图片，请将图片和指令在同一条消息中发出。")
            return

        target_dir = os.path.join(self.image_mgr.data_dir, "chefs")
        os.makedirs(target_dir, exist_ok=True)
        
        saved_count = 0
        
        async with aiohttp.ClientSession() as session:
            for img in images:
                content = None
                ext = ".jpg"
                if hasattr(img, 'url') and img.url and img.url.startswith('http'):
                    try:
                        async with session.get(img.url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                if "png" in img.url.lower(): ext = ".png"
                                elif "gif" in img.url.lower(): ext = ".gif"
                    except Exception as e:
                        logging.error(f"Download error: {e}")
                elif hasattr(img, 'file') and img.file and os.path.exists(img.file):
                    try:
                        with open(img.file, 'rb') as f:
                            content = f.read()
                        if img.file.lower().endswith('.png'): ext = ".png"
                        elif img.file.lower().endswith('.gif'): ext = ".gif"
                    except Exception:
                        pass
                
                if not content:
                    continue
                    
                save_path = os.path.join(target_dir, f"{chef_name}{ext}")
                if os.path.exists(save_path):
                    counter = 2
                    while True:
                        save_path = os.path.join(target_dir, f"{chef_name}_{counter}{ext}")
                        if not os.path.exists(save_path):
                            break
                        counter += 1
                        
                try:
                    with open(save_path, "wb") as f:
                        f.write(content)
                    saved_count += 1
                except Exception as e:
                    logging.error(f"Save error: {e}")
                    
        if saved_count > 0:
            self._reload_all_caches()
            yield event.make_result().message(f"✅ 上传厨师成功！\n共收录 {saved_count} 张【{chef_name}】至图库！")
        else:
            yield event.make_result().message("上传厨师失败：图片下载失败或平台限制导致无法读取。")
        return

    def _register_web_api(self):
        register_api = getattr(self.context, "register_web_api", None)
        if not callable(register_api):
            logging.warning("[ChisaEating] 当前 AstrBot 版本未提供 register_web_api。")
            return
            
        register_api(f"/{self.plugin_name}/list_images", self.page_list_images, ["GET"], "列出所有跨次元图库")
        register_api(f"/{self.plugin_name}/image-data", self.page_image_data, ["GET"], "获取跨次元图库原图数据")
        register_api(f"/{self.plugin_name}/add_ganfanren", self.page_add_ganfanren, ["POST"], "新增干饭人")
        register_api(f"/{self.plugin_name}/update_ganfanren", self.page_update_ganfanren, ["POST"], "更新干饭人语录")
        register_api(f"/{self.plugin_name}/upload_image", self.page_upload_image, ["POST"], "上传图片")
        register_api(f"/{self.plugin_name}/delete_image", self.page_delete_image, ["POST"], "删除图片")
        register_api(f"/{self.plugin_name}/delete_ganfanren", self.page_delete_ganfanren, ["POST"], "删除干饭人")
        register_api(f"/{self.plugin_name}/rename_image", self.page_rename_image, ["POST"], "重命名图片")



    async def page_list_images(self):
        """WebUI: 获取本地图库清单"""
        try:
            import os
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            data_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            
            result = {
                "food": {"common": [], "world1": [], "world2": [], "world3": [], "world4": [], "world5": []},
                "drink": {"common": [], "world1": [], "world2": [], "world3": [], "world4": [], "world5": []},
                "darkfood": {"common": [], "world1": [], "world2": [], "world3": [], "world4": [], "world5": []},
                "chefs": [],
                "memes": {"common": [], "world1": [], "world2": [], "world3": [], "world4": [], "world5": []},
                "ganfanren": {}
            }
            
            for cat in ["food", "drink", "darkfood"]:
                for world in result[cat].keys():
                    target_path = os.path.join(data_dir, cat, world)
                    if os.path.exists(target_path):
                        for file in os.listdir(target_path):
                            if file.startswith('.') or not os.path.isfile(os.path.join(target_path, file)): continue
                            result[cat][world].append(file)
                            
            chef_path = os.path.join(data_dir, "chefs")
            if os.path.exists(chef_path):
                for file in os.listdir(chef_path):
                    if not file.startswith('.') and os.path.isfile(os.path.join(chef_path, file)):
                        result["chefs"].append(file)
                        
            meme_path = os.path.join(data_dir, "memes")
            if os.path.exists(meme_path):
                for w in result["memes"].keys():
                    w_dir = os.path.join(meme_path, w)
                    if os.path.exists(w_dir):
                        for mood in os.listdir(w_dir):
                            m_dir = os.path.join(w_dir, mood)
                            if os.path.isdir(m_dir):
                                for file in os.listdir(m_dir):
                                    if not file.startswith('.') and os.path.isfile(os.path.join(m_dir, file)):
                                        result["memes"][w].append(f"{mood}/{file}")
                            
            gf_path = os.path.join(data_dir, "ganfanren")
            if os.path.exists(gf_path):
                for char in os.listdir(gf_path):
                    char_dir = os.path.join(gf_path, char)
                    if os.path.isdir(char_dir):
                        result["ganfanren"][char] = {"words": "", "images": []}
                        words_file = os.path.join(char_dir, "words.txt")
                        if os.path.exists(words_file):
                            try:
                                with open(words_file, 'r', encoding='utf-8') as lf:
                                    result["ganfanren"][char]["words"] = lf.read()
                            except Exception:
                                pass
                        for file in os.listdir(char_dir):
                            if not file.startswith('.') and file not in ("words.txt", "lines.txt") and os.path.isfile(os.path.join(char_dir, file)):
                                result["ganfanren"][char]["images"].append(file)
                                
            from quart import jsonify
            return jsonify({"status": "ok", "data": result}), 200
        except Exception as e:
            import traceback
            import logging
            from quart import jsonify
            logging.error(f"[ChisaEating] page_list_images error: {traceback.format_exc()}")
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_image_data(self):
        """WebUI: 发送真实图片 Base64 数据"""
        try:
            import os
            import base64
            import mimetypes
            
            path = request.args.get("path", "")
            if not path:
                return jsonify({"status": "error", "message": "No path provided"}), 400
                
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            base_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            full_path = os.path.abspath(os.path.join(base_dir, path))
            
            if not full_path.startswith(base_dir):
                return jsonify({"status": "error", "message": "Access denied"}), 403
                
            if not os.path.exists(full_path) or not os.path.isfile(full_path):
                if path == "Webui-PIC/Chisa.gif":
                    fallback_path = os.path.join(self.plugin_dir, "pages", "manager", "Chisa.gif")
                    if os.path.exists(fallback_path):
                        full_path = fallback_path
                    else:
                        return jsonify({"status": "error", "message": "File not found"}), 404
                else:
                    return jsonify({"status": "error", "message": "File not found"}), 404
                
            file_size = os.path.getsize(full_path)
            if file_size > 8 * 1024 * 1024:
                return jsonify({"status": "error", "message": "Image too large for preview"}), 413
                
            media_type = mimetypes.guess_type(full_path)[0] or "image/png"
            with open(full_path, "rb") as image_file:
                raw_bytes = image_file.read()
                data_url = f"data:{media_type};base64,{base64.b64encode(raw_bytes).decode('ascii')}"
                
            return jsonify({"status": "ok", "data_url": data_url}), 200
        except Exception as e:
            import traceback
            logging.error(f"[ChisaEating] page_image_data error: {traceback.format_exc()}")
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_add_ganfanren(self):
        """WebUI: 新增干饭人"""
        try:
            import os
            import base64
            import json
            
            payload = await request.get_json(silent=True)
            if not payload:
                raw_data = await request.get_data(as_text=True)
                try:
                    payload = json.loads(raw_data)
                except:
                    payload = {}

            name = payload.get("name", "").strip()
            words = payload.get("words", "").strip()
            images = payload.get("images", [])
            
            if not name:
                return jsonify({"status": "error", "message": "干饭人名字不能为空"}), 400
                
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            base_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            gf_dir = os.path.join(base_dir, "ganfanren", name)
            os.makedirs(gf_dir, exist_ok=True)
            
            words_path = os.path.join(gf_dir, "words.txt")
            with open(words_path, "w", encoding="utf-8") as f:
                f.write(words)
                
            for img in images:
                fname = img.get("filename")
                b64 = img.get("data", "")
                if fname and b64:
                    if b64.startswith("data:"):
                        b64 = b64.split(",")[1]
                    img_path = os.path.join(gf_dir, fname)
                    with open(img_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                        
            self._reload_all_caches()
            return jsonify({"status": "ok", "message": f"成功招募干饭人 {name}！"}), 200
        except Exception as e:
            import traceback
            logging.error(f"[ChisaEating] page_add_ganfanren error: {traceback.format_exc()}")
            return jsonify({"status": "error", "message": str(e)}), 500
