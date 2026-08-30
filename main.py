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

__version__ = "4.2.2"

@register("astrbot_plugin_chisa_still_eating", "Rua432", "4.2.2", "终极跨次元干饭系统")
class FlavorFusionUltimate(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.plugin_name = "astrbot_plugin_chisa_still_eating"
        self._register_web_api()
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        
        self.image_mgr = ImageManager(self.plugin_dir)
        self.data_mgr = FoodDataManager(config)
        self._dlc_best_node = None
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

    async def _download_and_extract_dlc_async(self, dlc_id, sha256_hash_str):
        self.is_downloading = True
        self.downloaded_bytes = 0
        self.download_total_bytes = 1 
        temp_zip_path = ""
        
        try:
            import hashlib
            import zipfile
            import os
            import aiohttp
            import asyncio
            
            node = await self._get_optimal_dlc_node()
            if node == "failed":
                raise Exception("所有测速节点均无响应")
                
            url = f"https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/Chisa_Dlc_Store/{dlc_id}.zip"
            if node != "direct":
                url = f"https://{node}/https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/Chisa_Dlc_Store/{dlc_id}.zip"
            
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            target_extract_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            temp_zip_path = os.path.join(target_extract_dir, f"{dlc_id}_temp.zip")
            os.makedirs(target_extract_dir, exist_ok=True)
            
            async with aiohttp.ClientSession(trust_env=(node == "direct")) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    if resp.status != 200:
                        raise Exception(f"HTTP {resp.status}")
                    
                    total = int(resp.headers.get('Content-Length', 0))
                    if total > 0:
                        self.download_total_bytes = total
                        
                    hasher = hashlib.sha256()
                    with open(temp_zip_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                            hasher.update(chunk)
                            self.downloaded_bytes += len(chunk)
                            
                    actual_sha256 = hasher.hexdigest()
                    
            if sha256_hash_str and actual_sha256 != sha256_hash_str:
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
                raise Exception(f"校验失败! 预期 {sha256_hash_str[:8]} 但得到 {actual_sha256[:8]}")
                
            def extract_safe(z_path, t_dir):
                with zipfile.ZipFile(z_path, 'r') as z_ref:
                    for z_info in z_ref.filelist:
                        if ".." in z_info.filename or z_info.filename.startswith("/") or z_info.filename.startswith("\\"):
                            raise Exception("Unsafe path in ZIP")
                    z_ref.extractall(t_dir)
                    
            try:
                await asyncio.to_thread(extract_safe, temp_zip_path, target_extract_dir)
                import logging
                logging.info(f"[Chisa DLC] 📦 DLC [{dlc_id}] 解压成功！")
            except Exception as e:
                import logging
                logging.error(f"[Chisa DLC] ❌ DLC [{dlc_id}] 解压失败: {e}")
                raise e
            
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
                
            self._reload_all_caches()
            
            # Sync downloaded state to downloaded.json for WebUI compatibility
            try:
                import json
                json_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "Shop", "index", "downloaded.json"))
                os.makedirs(os.path.dirname(json_path), exist_ok=True)
                records = []
                if os.path.exists(json_path):
                    with open(json_path, 'r', encoding='utf-8') as f:
                        try:
                            records = json.load(f)
                        except: pass
                if dlc_id not in records:
                    records.append(dlc_id)
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(records, f, ensure_ascii=False)
                import logging
                logging.info(f"[Chisa DLC] 📝 已将 [{dlc_id}] 写入商会已购清单。")
            except Exception as ex:
                import logging
                logging.error(f"[Chisa DLC] ⚠️ 写入已购清单失败: {ex}")
                
            return True
            
        except Exception as e:
            if temp_zip_path and os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)
            raise e
        finally:
            self.is_downloading = False
            self.downloaded_bytes = 0

    def _download_and_extract_assets(self):
        if self._is_download_thread_active:
            return
        self._is_download_thread_active = True
        self.is_downloading = True
        self.downloaded_bytes = 0
        self.download_msg = "正在从远程拉取图库源文件 (约 99.2MB)，请耐心等待..."
        
        import concurrent.futures
        import time
        import requests
        import hashlib
        import zipfile
        import shutil

        logging.info("[ChisaEating] 🚀 开始图库部署准备...检测到国内网络环境，启动多线程智能测速引擎。")
        logging.info("[ChisaEating] 📡 正在并发探测 4 个 Github 加速节点 (Timeout=10s)...")

        base_url = "https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/Chisa_Dlc_Store/fd0000.zip"
        mirrors = [
            f"https://gh-proxy.com/{base_url}",
            f"https://hk.gh-proxy.com/{base_url}",
            f"https://edgeone.gh-proxy.com/{base_url}",
            f"https://gh.dpik.top/{base_url}"
        ]

        def test_speed(url):
            start = time.time()
            try:
                r = requests.get(url, stream=True, timeout=30, proxies={"http": None, "https": None})
                r.raise_for_status()
                latency = int((time.time() - start) * 1000)
                r.close()
                return url, latency
            except:
                return url, float('inf')

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_url = {executor.submit(test_speed, url): url for url in mirrors}
            
            # 第一阶段：只等 10 秒
            done, not_done = concurrent.futures.wait(future_to_url.keys(), timeout=10)
            
            valid_results = {}
            for future in done:
                url = future_to_url[future]
                try:
                    _, lat = future.result()
                    results[url] = lat
                    if lat != float('inf'):
                        valid_results[url] = lat
                except:
                    results[url] = float('inf')
                    
            if not valid_results and not_done:
                logging.info("[ChisaEating] ⏳ 10秒内未捕获到极速节点，自动进入最高 30 秒深度探测模式...")
                done2, not_done2 = concurrent.futures.wait(not_done, timeout=20)
                for future in done2:
                    url = future_to_url[future]
                    try:
                        _, lat = future.result()
                        results[url] = lat
                        if lat != float('inf'):
                            valid_results[url] = lat
                    except:
                        results[url] = float('inf')
                for future in not_done2:
                    url = future_to_url[future]
                    results[url] = float('inf')
            else:
                for future in not_done:
                    url = future_to_url[future]
                    results[url] = float('inf')

        logging.info("[ChisaEating] 📊 节点测速报告 (TTFB):")
        best_url = None
        best_latency = float('inf')
        for url in mirrors:
            lat = results.get(url, float('inf'))
            hostname = url.split('/')[2]
            if lat != float('inf'):
                logging.info(f"    👉 [{hostname}] 响应延迟: {lat}ms")
                if lat < best_latency:
                    best_latency = lat
                    best_url = url
            else:
                logging.info(f"    👉 [{hostname}] 状态: 🔴 超时/连通失败/过慢被弃用")

        urls_to_try = []
        if best_url:
            hostname = best_url.split('/')[2]
            logging.info(f"[ChisaEating] 👑 测速决议：最优节点锁定为 [{hostname}] ({best_latency}ms)。")
            logging.info("[ChisaEating] ⚡ 强制屏蔽全局代理 (Proxies disabled)，使用物理宽带直连开始高速下载！")
            urls_to_try.append({"url": best_url, "proxies": {"http": None, "https": None}, "desc": f"节点 [{hostname}]"})
        else:
            logging.warning("[ChisaEating] ❌ 警告：所有国内加速镜像均无法连通（全部超时）！")

        logging.info("[ChisaEating] 🔄 加入 Github 官方直连节点作为兜底...")
        urls_to_try.append({"url": base_url, "proxies": None, "desc": "Github 官方节点 (遵循全局代理)"})

        try:
            zip_path = os.path.join(self.image_mgr.data_dir, "assets_temp.zip")
            os.makedirs(self.image_mgr.data_dir, exist_ok=True)
            TARGET_HASH = "18648dfbd827cc69b1e0c627058d15a5b0a5622967a2a11b852cc8098df499c9"
            success = False

            for item in urls_to_try:
                url = item["url"]
                proxies = item["proxies"]
                desc = item["desc"]
                
                try:
                    logging.info(f"[ChisaEating] ⬇️ 正在通过 {desc} 下载资源包 (99.2MB)...")
                    self.downloaded_bytes = 0
                    response = requests.get(url, stream=True, timeout=120, proxies=proxies)
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
                            f"[ChisaEating] ⚠️ 安全警告：下载的资源包哈希值不匹配！\n"
                            f"预期: {TARGET_HASH}\n"
                            f"实际: {downloaded_hash}\n"
                            "将自动删除危险文件，尝试下一个节点..."
                        )
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                        continue
                        
                    success = True
                    break
                except Exception as e:
                    logging.warning(f"[ChisaEating] ⚠️ 节点 {desc} 下载异常中断: {e}")
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                    if url != base_url:
                        logging.info("[ChisaEating] 🔄 正在启动终极兜底方案：切换至 Github 官方直连节点...")
                        logging.info("[ChisaEating] 🌐 已恢复系统代理继承 (遵循 AstrBot 代理配置)，继续下载！")

            if success:
                self.download_msg = "图库包拉取完成并经过 SHA-256 安全校验，正在解压部署..."
                logging.info("[ChisaEating] ✅ 资源包下载并校验通过，开始解压...")
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        extract_tmp = os.path.join(self.image_mgr.data_dir, "extract_tmp")
                        extract_tmp_abs = os.path.abspath(extract_tmp)
                        for member in zip_ref.infolist():
                            target_path = os.path.abspath(os.path.join(extract_tmp_abs, member.filename))
                            if not target_path.startswith(extract_tmp_abs):
                                logging.warning(f"[ChisaEating] ⚠️ 检测到 Zip-Slip 路径穿越试图: {member.filename}，已拦截！")
                                continue
                            zip_ref.extract(member, extract_tmp_abs)
                        
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
                                
                    logging.info("[ChisaEating] 🎉 默认图库解压部署完成！")
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
                logging.error("[ChisaEating] ❌ 所有图库加速节点均拉取超时或哈希校验失败，当前后台取消下载，请通过 Readme 手动下载安装。")
            
            if self.config.get("force_download_assets", False):
                self.config["force_download_assets"] = False
                
        finally:
            self.is_downloading = False
            self.downloaded_bytes = 0
            self._is_download_thread_active = False

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
        logging.info(f"[ChisaEating v3.8.51] 📋 已更新可用干饭人清单到 plugin_data 目录，共 {len(names)} 名")

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
            if not name or ".." in name or "/" in name or "\\" in name: return jsonify({"status":"error"}), 400
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            try: base_data_path = get_astrbot_data_path()
            except: base_data_path = "data"
            if ".." in name or "/" in name or "\\" in name: return jsonify({"status": "error", "message": "非法名称"}), 400
            gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren", name))
            base_gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren"))
            if not gf_dir.startswith(base_gf_dir): return jsonify({"status": "error", "message": "非法越权访问"}), 403
            base_gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren"))
            if not gf_dir.startswith(base_gf_dir): return jsonify({"status": "error", "message": "非法越权访问"}), 403
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
                
            if ".." in name or "/" in name or "\\" in name: return jsonify({"status": "error", "message": "非法名称"}), 400
            gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren", name))
            base_gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren"))
            if not gf_dir.startswith(base_gf_dir): return jsonify({"status": "error", "message": "非法越权访问"}), 403
            base_gf_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "ganfanren"))
            if not gf_dir.startswith(base_gf_dir): return jsonify({"status": "error", "message": "非法越权访问"}), 403
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
            if ".." in world or "/" in world or "\\" in world: world = ""
            mode = payload.get("mode", "batch")
            single_chef = payload.get("single_chef", "").strip()
            single_dish = payload.get("single_dish", "").strip()
            if ".." in single_chef or "/" in single_chef or "\\" in single_chef: single_chef = ""
            if ".." in single_dish or "/" in single_dish or "\\" in single_dish: single_dish = ""
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
                char_name = payload.get("char_name", "")
                if ".." in char_name or "/" in char_name or "\\" in char_name: char_name = ""
                target_dir = os.path.join(base_dir, "ganfanren", char_name)
            else:
                return jsonify({"status":"error", "message": "Invalid category"}), 400
                
            target_dir = os.path.abspath(target_dir)
            if not target_dir.startswith(os.path.abspath(base_dir)): return jsonify({"status": "error", "message": "跨目录上传拒绝"}), 403
            os.makedirs(target_dir, exist_ok=True)
            
            for f in files:
                fname = f.get("filename", "")
                if ".." in fname or "/" in fname or "\\" in fname: continue
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
                img_path = os.path.abspath(os.path.join(target_dir, fname))
                if not img_path.startswith(os.path.abspath(target_dir)): continue
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

        uid = str(event.get_sender_id())
        
        import time
        import re
        import asyncio
        import os
        
        if uid in self._shop_sessions:
            session = self._shop_sessions[uid]
            if time.time() - session['time'] > 60:
                del self._shop_sessions[uid]
            else:
                choice = msg_text.strip()
                if choice in ['1', '2', '3']:
                    del self._shop_sessions[uid]
                    catalog = self._read_catalog()
                    if not catalog:
                        yield event.make_result().message("⚠️ 无法读取目录数据，请重新同步。")
                        event.stop_event()
                        return
                        
                    mapping = {
                        '1': {'cats': ['gf', 'cf', 'gd'], 'title': '千小妹商会 - 招募通道', 'cmd_format': '招募{id}'},
                        '2': {'cats': ['fd', 'dr'], 'title': '千小妹商会 - 餐饮通道', 'cmd_format': '进货{id}'},
                        '3': {'cats': ['dk'], 'title': '千小妹商会 - 次元裂缝', 'cmd_format': '黑魔法召唤{id}'}
                    }
                    
                    config = mapping[choice]
                    results = {}
                    for item in catalog:
                        cat = item.get('cat', '')
                        if cat in config['cats']:
                            if cat not in results: results[cat] = []
                            results[cat].append(item)
                            
                    msg = f"📦 {config['title']} 📦\n*回复\"{config['cmd_format'].format(id='[编号]')}\"或\"{config['cmd_format'].format(id='编号')}\"即可下载对应包体\n*也可以到AstrbotWebUI浏览商品，还有预览图哦\n\n"
                    
                    emoji_map = {
                        'fd': '🍔 食品区', 'dr': '🧋 饮品区', 
                        'gf': '🏃 干饭人', 'cf': '👨‍🍳 大厨', 'gd': '🌸 导游MEME', 
                        'dk': '☠️ 黑暗料理'
                    }
                    
                    for cat_key in config['cats']:
                        msg += f"{emoji_map.get(cat_key, cat_key)}\n"
                        if cat_key in results and results[cat_key]:
                            for item in results[cat_key]:
                                msg += f"·[{item.get('id', '')}] {item.get('title', '')}\n"
                        else:
                            msg += "·这个分类暂时还没有商品上架·\n"
                        msg += "\n"
                            
                    async for res in self._send_forward_msg(event, "千小妹商会商品列表", msg.strip()):
                        yield res
                    event.stop_event()
                    return
                elif len(choice) <= 2: 
                    self._shop_sessions[uid]['time'] = time.time()
                    yield event.make_result().message("输入错误哦，请回复 1、2 或 3")
                    event.stop_event()
                    return
                else:
                    del self._shop_sessions[uid]

        if msg_text.strip() == "千小妹商会":
            if not self._is_admin(event):
                yield event.make_result().message("哼！千小妹商会重地，闲人免进！只有签了契约的管理员才能进去进货哦~")
                event.stop_event()
                return
                
            cat_path = self._get_catalog_path()
            if not os.path.exists(cat_path):
                yield event.make_result().message("仓库空空如也！是否进行千小妹商会信息同步？\n（请回复：/千小妹商会信息同步）")
                event.stop_event()
                return
                
            self._shop_sessions[uid] = {'time': time.time()}
            yield event.make_result().message("🎀 千小妹商会营业中 🎀\n欢迎老板！请在 60 秒内回复数字选择进货通道：\n1️⃣ 干饭人/大厨/导游招募\n2️⃣ 云食品/云饮品仓库\n3️⃣ 黑暗料理次元裂缝")
            event.stop_event()
            return
            
        if msg_text.strip() in ["/千小妹商会信息同步", "千小妹商会信息同步拉取Json", "千小妹商会信息同步"]:
            if not self._is_admin(event):
                yield event.make_result().message("只有管理员可以同步商会信息哦！")
                event.stop_event()
                return
                
            yield event.make_result().message("正在联系商会总仓...请稍等片刻哦~")
            
            node = await self._get_optimal_dlc_node()
            if node == "failed":
                yield event.make_result().message("所有节点响应超时，同步失败，请稍后再试！")
                event.stop_event()
                return
                
            original_url = "https://raw.githubusercontent.com/dddada123/astrbot_plugin_chisa_still_eating_photo/main/index/catalog.json"
            url = original_url
            if node != "direct":
                url = f"https://{node}/{original_url}"
            import aiohttp
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            cat_path = self._get_catalog_path()
                            os.makedirs(os.path.dirname(cat_path), exist_ok=True)
                            with open(cat_path, 'wb') as f:
                                f.write(content)
                            yield event.make_result().message("✅ 同步完成！请再次输入 【千小妹商会】 开始逛街~")
                        else:
                            yield event.make_result().message(f"同步失败，节点返回状态码: {resp.status}")
            except Exception as e:
                yield event.make_result().message(f"同步异常: {str(e)}")
            event.stop_event()
            return
            
        dl_match = re.match(r'^(进货|招募|黑魔法召唤)\[?([a-z]{2}\d{4})\]?$', msg_text.strip(), re.IGNORECASE)
        if dl_match:
            if not self._is_admin(event):
                yield event.make_result().message("只有管理员才能操作商会进货哦！")
                event.stop_event()
                return
                
            dlc_id = dl_match.group(2).lower()
            
            if self.is_downloading:
                pct = 0
                if hasattr(self, 'download_total_bytes') and getattr(self, 'download_total_bytes', 0) > 0:
                    pct = int((self.downloaded_bytes / self.download_total_bytes) * 100)
                yield event.make_result().message(f"📦 千小妹正在狂奔搬运中... 进度 [{pct}%]，请等待当前进货完成后再操作哦~")
                event.stop_event()
                return
                
            catalog = self._read_catalog()
            if not catalog:
                yield event.make_result().message("⚠️ 无法读取目录数据，请先输入 千小妹商会 进行同步。")
                event.stop_event()
                return
                
            target_item = next((item for item in catalog if item.get('id', '').lower() == dlc_id), None)
            if not target_item:
                yield event.make_result().message(f"找不到编号为 {dlc_id} 的商品呢，老板是不是记错啦？")
                event.stop_event()
                return
                
            sha256 = target_item.get('sha256', '')
            yield event.make_result().message(f"收到！千小妹这就去进货 {dlc_id}，请稍等片刻...")
            
            async def trigger_download():
                import logging
                try:
                    res = await self._download_and_extract_dlc_async(dlc_id, sha256)
                    if res:
                        from astrbot.core.message.message_event_result import MessageChain
                        from astrbot.api.message_components import Plain
                        success_msg = f"🎉 千小妹已经把 [{dlc_id}] 搬到后厨啦！快去尝尝吧~\n(💡 提示：如果图片没能加载到插件内，直接在管理面板重载插件就可以啦~)"
                        logging.info(f"[Chisa DLC] ✅ 群聊指令进货 [{dlc_id}] 完美落库！")
                        await event.send(MessageChain([Plain(success_msg)]))
                except Exception as e:
                    logging.error(f"[Chisa DLC] ❌ 群聊触发下载 {dlc_id} 失败: {e}")
                    try:
                        from astrbot.core.message.message_event_result import MessageChain
                        from astrbot.api.message_components import Plain
                        await event.send(MessageChain([Plain(f"❌ 进货遭遇次元风暴: {str(e)}")]))
                    except: pass
            
            asyncio.create_task(trigger_download())
            event.stop_event()
            return

        
        is_plugin_cmd = False
        if "进货" in msg_text or "招募" in msg_text or "黑魔法召唤" in msg_text:
            is_plugin_cmd = True
        if ("/加菜" in msg_text or "加菜" in msg_text or "/上传厨师" in msg_text or "上传厨师" in msg_text or 
            "帮助" in msg_text or "吃什么" in msg_text or "喝什么" in msg_text or "特产" in msg_text or 
            "特饮" in msg_text or "吃饭" in msg_text or "料理" in msg_text or "召唤" in msg_text or "特供" in msg_text) and "千小妹图库下载进度" not in msg_text:
            is_plugin_cmd = True
            
        if self.is_downloading and is_plugin_cmd:
            if hasattr(self, '_is_download_thread_active') and self._is_download_thread_active:
                mb = self.downloaded_bytes / (1024 * 1024)
                progress_msg = f"【千小妹基础图库下载进度】\n正在为您搬运跨次元美食资源...下载完成后即可正常使用以及查看帮助\n当前已下载: {mb:.2f} MB / 99.20 MB"
                yield event.make_result().message(progress_msg)
                event.stop_event()
                return
            else:
                pct = 0
                if hasattr(self, 'download_total_bytes') and getattr(self, 'download_total_bytes', 0) > 0:
                    pct = int((self.downloaded_bytes / self.download_total_bytes) * 100)
                progress_msg = f"📦 千小妹正在狂奔搬运中... 当前进货进度 [{pct}%]，请稍后再操作哦~"
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
                yield event.make_result().message(f"【千小妹下载进度】\n正在为您搬运跨次元美食资源...下载完成后即可正常使用以及查看帮助\n当前已下载: {mb:.2f} MB / 99.20 MB")
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
                    yield event.make_result().message("【千小妹提示】已收到显式确认！开始从 Github 拉取并更新图库 (约99.2MB)，请查看后台日志或稍后重试抽卡。回复/千小妹图库下载进度或任意吃什么命令可查看当前下载进度。")
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
            help_text = """🌸 【千小妹跨次元干饭指南 v4.1.0】 🌸
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
🛒 千小妹商会 (云端无缝进货)
💬 千小妹商会：唤出千小妹云端商会菜单，输入数字极速点单进货！
💬 进货[编号] / 招募[编号] / 黑魔法召唤[编号]：直接输入对应DLC编号，将官方商品一键装入本地后厨。
💬 /千小妹商会信息同步：强制拉取商会最新商品名录。
---
⚙️ 系统与图库管理 (注：需在AstrBot后台配置管理员)
💬 千小妹速查：极速调出可用短指令表。
💬 千小妹图库下载进度：随时查看后台图库的拉取进度。
💬 更新千小妹图库：强制进行99.2MB图包的安全拉取。
💬 【加菜格式】：加菜 [世界] [分类] [菜名]
⚠️ (参数之间必须打空格，且图片要和文字发在同一条消息里！)
💡 举例：加菜 三次元 食物 肯德基肉霸堡 (带图)
💬 【加大厨格式】：上传厨师 [厨师名]
💡 举例：上传厨师 刻晴 (带图)
⚠️ 若您是在服务器后台手动放入新图片或TXT，请务必在WebUI点击【重载插件】或群内发送 更新千小妹图库 刷新缓存。

(📝 注：以上所有指令均不受机器人名字影响。发“小爱吃什么”也能完美触发哦！)"""
            async for res in self._send_forward_msg(event, "千小妹帮助文档", help_text):
                yield res
            event.stop_event()
            re
        if msg_text == "千小妹速查" or msg_text == "/千小妹速查":
            quick_msg = (
                "📌 【千小妹速查表】\n\n"
                "🍔 基础功能\n"
                "· 吃什么 / 喝点啥\n"
                "· 来点现实的食物 / 鸣潮特产\n\n"
                "👑 进阶与整活\n"
                "· 来点黑暗料理\n"
                "· 召唤[某人]下厨 / [某人]特供料理\n\n"
                "🛒 商会系统 (需管理员)\n"
                "· 千小妹商会\n"
                "· 进货[编号] / 招募[编号] / 黑魔法召唤[编号]\n"
                "· /千小妹商会信息同步\n\n"
                "⚙️ 管理指令 (需管理员)\n"
                "· 更新千小妹图库\n"
                "· 千小妹图库下载进度\n"
                "· 加菜 [世界] [分类] [菜名] (带图)\n"
                "· 上传厨师 [厨师名] (带图)"
            )
            async for res in self._send_forward_msg(event, "千小妹短指令速查表", quick_msg):
                yield res
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
随后在群内发送 /更新千小妹图库 即可触发 99.2MB 图包的安全拉取。

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
随后在群内发送 /更新千小妹图库 即可触发 99.2MB 图包的安全拉取。

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

    

    

    async def _send_forward_msg(self, event, title: str, text_content: str):
        if not self.config.get("forward_long_text", True):
            yield event.make_result().message(text_content)
            return
            
        try:
            from astrbot.api.message_components import Forward, Node, Plain
            from astrbot.core.message.components import MessageChain
            
            # Construct Node. Use bot's own ID to ensure bot's avatar is displayed.
            bot_id = getattr(event, "bot_id", None)
            if not bot_id and hasattr(event.message_obj, "self_id"):
                bot_id = event.message_obj.self_id
            if not bot_id:
                bot_id = str(event.get_sender_id()) # Extreme fallback
            
            node_kwargs = {
                "uin": str(bot_id),
                "name": title,
                "content": [Plain(text_content)]
            }
            try:
                node = Node(custom_name=title, uin=str(bot_id), content=[Plain(text_content)])
            except TypeError:
                node = Node(**node_kwargs)
                
            yield event.make_result().message(Forward([node]))
            return
        except ImportError:
            # Fallback for old Astrbot versions without Forward
            pass
        except Exception as e:
            import logging
            logging.error(f"[Chisa DLC] Forward component failed: {e}")
            
        try:
            # Raw fallback for Nakuru/Aiocqhttp if possible
            provider = getattr(event, "client", getattr(event, "bot", getattr(event, "provider", None)))
            if provider and hasattr(provider, "api") and hasattr(provider.api, "call_action"):
                group_id = getattr(event.message_obj, "group_id", None)
                bot_id = getattr(event, "bot_id", None)
                if not bot_id and hasattr(event.message_obj, "self_id"):
                    bot_id = event.message_obj.self_id
                if not bot_id:
                    bot_id = str(event.get_sender_id())
                messages = [{
                    "type": "node",
                    "data": {
                        "name": title,
                        "uin": str(bot_id),
                        "content": [{"type": "text", "data": {"text": text_content}}]
                    }
                }]
                if group_id:
                    await provider.api.call_action('send_group_forward_msg', group_id=int(group_id), messages=messages)
                else:
                    await provider.api.call_action('send_private_forward_msg', user_id=int(event.get_sender_id()), messages=messages)
                
                event.stop_event()
                return
        except Exception as e:
            import logging
            logging.error(f"[Chisa DLC] Raw API forward failed: {e}")
            
        yield event.make_result().message(text_content)
    def _is_admin(self, event):
        uid = str(event.get_sender_id())
        admin_users = [str(x).strip() for x in self.config.get("admin_users", []) if str(x).strip()]
        if not admin_users or uid not in admin_users:
            return False
        return True

    def _get_catalog_path(self):
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            base_data_path = get_astrbot_data_path()
        except ImportError:
            base_data_path = "data"
        import os
        return os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "Shop", "index", "catalog.json"))

    def _read_catalog(self):
        import os
        import json
        cat_path = self._get_catalog_path()
        if not os.path.exists(cat_path):
            return None
        with open(cat_path, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
            if isinstance(data, dict) and "data" in data:
                return data["data"]
            return data
            
    _shop_sessions = {}
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
        
        # DLC 商城 API 注册
        register_api(f"/{self.plugin_name}/dlc_catalog", self.page_dlc_catalog, ["GET"], "获取本地DLC缓存目录")
        register_api(f"/{self.plugin_name}/fetch_dlc_catalog", self.page_fetch_dlc_catalog, ["POST"], "拉取线上DLC目录")
        register_api(f"/{self.plugin_name}/store_banner", self.page_store_banner, ["GET"], "获取商店海报本地缓存")
        register_api(f"/{self.plugin_name}/last_custom_repo", self.page_get_last_custom_repo, ["GET"], "获取最近连接的工坊仓库")
        register_api(f"/{self.plugin_name}/workshop_bookmarks", self.page_get_workshop_bookmarks, ["GET"], "读取工坊书架")
        register_api(f"/{self.plugin_name}/save_workshop_bookmarks", self.page_save_workshop_bookmarks, ["POST"], "保存工坊书架")
        register_api(f"/{self.plugin_name}/dlc_metadata", self.page_dlc_metadata, ["GET"], "获取商店本地元数据")
        register_api(f"/{self.plugin_name}/skin_asset", self.page_skin_asset, ["GET"], "准备皮肤资源(带缓存)")
        register_api(f"/{self.plugin_name}/skin_asset_chunk", self.page_skin_asset_chunk, ["GET"], "分块读取皮肤资源")
        register_api(f"/{self.plugin_name}/skin_index", self.page_skin_index, ["GET"], "拉取皮肤源索引")
        register_api(f"/{self.plugin_name}/skin_get", self.page_skin_get, ["POST"], "拉取皮肤配置")
        register_api(f"/{self.plugin_name}/skin_local", self.page_skin_local, ["GET"], "列出本地皮肤缓存")
        register_api(f"/{self.plugin_name}/skin_delete", self.page_skin_delete, ["POST"], "删除本地皮肤缓存")
        register_api(f"/{self.plugin_name}/skin_sources", self.page_skin_sources, ["GET"], "读取皮肤源列表")
        register_api(f"/{self.plugin_name}/save_skin_sources", self.page_save_skin_sources, ["POST"], "保存皮肤源列表")
        register_api(f"/{self.plugin_name}/skin_pref", self.page_get_skin_pref, ["GET"], "读取皮肤偏好")
        register_api(f"/{self.plugin_name}/save_skin_pref", self.page_save_skin_pref, ["POST"], "保存皮肤偏好")
        register_api(f"/{self.plugin_name}/fetch_single_cover", self.page_fetch_single_cover, ["POST"], "增量拉取单张DLC封面")
        register_api(f"/{self.plugin_name}/dlc_cover", self.page_dlc_cover, ["GET"], "获取本地DLC缓存封面")
        register_api(f"/{self.plugin_name}/download_dlc", self.page_download_dlc, ["POST"], "下载DLC")
        register_api(f"/{self.plugin_name}/test_reflection", self.page_test_reflection, ["GET"], "test")
        register_api(f"/{self.plugin_name}/get_dlc_downloaded", self.page_get_dlc_downloaded, ["GET"], "获取已下载DLC记录")
        register_api(f"/{self.plugin_name}/get_download_progress", self.page_get_download_progress, ["POST"], "获取DLC下载进度")
        register_api(f"/{self.plugin_name}/delete_ganfanren", self.page_delete_ganfanren, ["POST"], "删除干饭人")
        register_api(f"/{self.plugin_name}/rename_image", self.page_rename_image, ["POST"], "重命名图片")
        register_api(f"/{self.plugin_name}/frontend_log", self.page_frontend_log, ["POST"], "前端日志打印")




    
    async def page_frontend_log(self):
        """接收前端传来的日志并打印，用于调试并发加载和皮肤应用"""
        try:
            import logging
            from quart import request, jsonify
            payload = await request.get_json(silent=True) or {}
            msg = payload.get("msg", "")
            if msg:
                logging.info(f"[Chisa Skin Front] {msg}")
            return jsonify({"status": "success"})
        except Exception:
            from quart import jsonify
            return jsonify({"status": "error"}), 500

    async def page_test_reflection(self):
        try:
            from quart import jsonify
            import astrbot.api.message_components as mc
            return jsonify({"components": dir(mc)})
        except Exception as e:
            return jsonify({"error": str(e)})
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

    
    async def _get_optimal_dlc_node(self) -> str:
        if getattr(self, '_dlc_best_node', None) is not None:
            return self._dlc_best_node
            
        import asyncio
        import aiohttp
        import time
        import logging
        
        logging.info("[Chisa DLC] 🌐 开始智能并发测速以寻找最优下载节点...")
        test_url = "https://raw.githubusercontent.com/dddada123/astrbot_plugin_chisa_still_eating_photo/main/index/catalog.json"
        
        nodes = [
            "gh-proxy.com",
            "hk.gh-proxy.com",
            "gh.dpik.top",
            "edgeone.gh-proxy.com"
        ]
        
        async def test_node(node):
            start = time.time()
            url = f"https://{node}/{test_url}" if node else test_url
            try:
                async with aiohttp.ClientSession(trust_env=False) as session:
                    async with session.get(url, timeout=10) as resp:
                        resp.raise_for_status()
                        await resp.read()
                        return node, int((time.time() - start) * 1000)
            except:
                return node, float('inf')
                
        tasks = [asyncio.create_task(test_node(n)) for n in nodes]
        done, pending = await asyncio.wait(tasks, timeout=10, return_when=asyncio.ALL_COMPLETED)
        
        best_node = None
        best_lat = float('inf')
        
        for task in done:
            try:
                node, lat = task.result()
                if lat != float('inf'):
                    logging.info(f"[Chisa DLC] 👉 [{node or 'direct'}] 响应延迟: {lat}ms")
                    if lat < best_lat:
                        best_lat = lat
                        best_node = node
                else:
                    logging.info(f"[Chisa DLC] 👉 [{node or 'direct'}] 状态: 🔴 超时/连通失败")
            except:
                pass
                
        if best_node is None and pending:
            logging.info("[Chisa DLC] ⏳ 10秒内未捕获到极速节点，自动进入最高 30 秒深度探测模式...")
            done2, pending2 = await asyncio.wait(pending, timeout=20, return_when=asyncio.ALL_COMPLETED)
            for task in done2:
                try:
                    node, lat = task.result()
                    if lat != float('inf'):
                        logging.info(f"[Chisa DLC] 👉 [{node or 'direct'}] 响应延迟: {lat}ms")
                        if lat < best_lat:
                            best_lat = lat
                            best_node = node
                    else:
                        logging.info(f"[Chisa DLC] 👉 [{node or 'direct'}] 状态: 🔴 超时/连通失败")
                except:
                    pass
                    
        if best_node is not None:
            logging.info(f"[Chisa DLC] 👑 测速决议：最优节点锁定为 [{best_node or 'direct'}] ({best_lat}ms)。")
            self._dlc_best_node = best_node
            return best_node
            
        logging.warning("[Chisa DLC] ❌ 国内加速镜像均不可用，回退到支持系统代理的 direct。")
        self._dlc_best_node = "direct"
        return "direct"

    def _get_store_dir(self, store_type, repo_id=None):
        import os
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        try:
            base_data_path = get_astrbot_data_path()
        except ImportError:
            base_data_path = "data"
        plugin_dir = os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating")
        
        if store_type == "custom":
            # 修复穿透 Bug: custom 模式但 repo_id 为空时，绝不允许落入官方 Shop 目录
            if not repo_id:
                return os.path.join(plugin_dir, "Webui-PIC", "Workshop", "_empty_", "index")
            safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(repo_id))
            return os.path.join(plugin_dir, "Webui-PIC", "Workshop", safe_id, "index")
        else:
            return os.path.join(plugin_dir, "Webui-PIC", "Shop", "index")

    def _get_banner_dir(self):
        import os
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        try:
            base_data_path = get_astrbot_data_path()
        except ImportError:
            base_data_path = "data"
        return os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "banner")

    async def page_dlc_catalog(self):
        try:
            import os
            import json
            from quart import jsonify, request
            
            store_type = request.args.get("store_type", "official")
            repo_id = request.args.get("repo_id", "")
            
            # 双保险: custom 模式必须携带 repo_id，否则直接返回 missing，防止官方数据被误渲染到工坊
            if store_type == "custom" and not repo_id.strip():
                return jsonify({"status": "missing"})
                
            index_dir = self._get_store_dir(store_type, repo_id)
            catalog_path = os.path.join(index_dir, "catalog.json")
            if not os.path.exists(catalog_path):
                return jsonify({"status": "missing"})
                
            with open(catalog_path, 'r', encoding='utf-8-sig') as f:
                data = json.load(f)
                
            meta_path = os.path.join(index_dir, "metadata.json")
            meta_data = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8-sig') as mf:
                        meta_data = json.load(mf)
                except Exception:
                    meta_data = {}
                    
            return jsonify({"status": "success", "data": data, "metadata": meta_data})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_fetch_dlc_catalog(self):
        try:
            import os
            import aiohttp
            import asyncio
            import json
            import re
            from quart import jsonify, request
            
            payload = await request.get_json(silent=True) or {}
            node = payload.get("node", "smart")
            custom_url = payload.get("custom_url", "").strip()
            store_type = payload.get("store_type", "official")
            repo_id = payload.get("repo_id", "")
            
            # 防护: 工坊模式必须携带仓库地址，防止把官方目录数据拉写到错误路径
            if store_type == "custom" and not custom_url:
                return jsonify({"status": "error", "message": "请先输入第三方仓库地址"}), 400
                
            # ---------- 仓库地址标准化: 从任意 GitHub URL 形态中提取 owner/repo ----------
            def extract_owner_repo(url):
                m = re.search(r"github\.com[/:]([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/|$)", url)
                if m:
                    return m.group(1), m.group(2)
                return None, None

            owner, repo_name = "dddada123", "astrbot_plugin_chisa_still_eating_photo"
            if store_type == "custom" and custom_url:
                c_owner, c_repo = extract_owner_repo(custom_url)
                if not c_owner or not c_repo:
                    return jsonify({"status": "error", "message": "无法识别仓库地址，请填写形如 https://github.com/作者名/仓库名 的完整地址"}), 400
                owner, repo_name = c_owner, c_repo

            # 三级源: raw 短格式 → raw refs 格式 → jsDelivr CDN (国内可达性最好，且绕开代理缓存怪癖)
            source_bases = [
                f"https://raw.githubusercontent.com/{owner}/{repo_name}/main",
                f"https://raw.githubusercontent.com/{owner}/{repo_name}/refs/heads/main",
                f"https://cdn.jsdelivr.net/gh/{owner}/{repo_name}@main",
            ]
            # 兼容: 用户自定义 raw_base 时 (旧逻辑入参) 仍以标准化结果为准

            if node == "smart":
                node = await self._get_optimal_dlc_node()
                
            import logging
            
            async def _do_fetch(url, use_node):
                try:
                    async with aiohttp.ClientSession(trust_env=(use_node in ("direct", ""))) as session:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                            if resp.status == 200:
                                return await resp.read()
                except Exception:
                    pass
                return None
                
            async def _fetch_via(base, path):
                """对单个源尝试拉取。raw 源: 节点代理优先→直连兜底; jsDelivr 源: CDN直连优先→节点代理兜底
                (gh-proxy 类代理通常只反代 GitHub 域名，对 cdn.jsdelivr.net 会拒绝)"""
                if "jsdelivr" in base:
                    content = await _do_fetch(f"{base}/{path}", "direct")
                    if content is None and node != "direct":
                        content = await _do_fetch(f"https://{node}/{base}/{path}", node)
                    return content
                url = f"{base}/{path}"
                if node and node != "direct":
                    url = f"https://{node}/{url}"
                content = await _do_fetch(url, node)
                if content is None and node != "direct":
                    content = await _do_fetch(f"{base}/{path}", "direct")
                return content
                
            async def fetch_repo_file(path):
                """遍历三级源直到拿到内容; 返回 (content, source_desc)"""
                for idx, base in enumerate(source_bases):
                    content = await _fetch_via(base, path)
                    if content:
                        return content, f"source{idx+1}({base.split('/')[2]})"
                return None, "ALL_SOURCES_FAILED"
                
            # catalog 与 metadata 并发拉取 (3.9.25 误为串行，节点限流时第二个请求更易失败)
            (catalog_content, cat_src), (meta_content, meta_src) = await asyncio.gather(
                fetch_repo_file("index/catalog.json"),
                fetch_repo_file("Chisa_DLC_Metadata.json")
            )
            
            logging.info(f"[Chisa DLC] 📥 拉取结果 via [{node or 'direct'}]: catalog={'OK' if catalog_content else 'FAIL'} ({cat_src}) metadata={'OK' if meta_content else 'FAIL'} ({meta_src})")
            
            if not catalog_content:
                if payload.get("node", "smart") == "smart":
                    logging.warning(f"[Chisa DLC] 锁定节点下载失败，清除测速缓存！")
                    self._dlc_best_node = None
                return jsonify({"status": "error", "message": "Failed to fetch catalog.json"}), 500
                
            index_dir = self._get_store_dir(store_type, repo_id)
            os.makedirs(index_dir, exist_ok=True)
            
            with open(os.path.join(index_dir, "catalog.json"), 'wb') as f:
                f.write(catalog_content)
                
            meta_path = os.path.join(index_dir, "metadata.json")
            
            meta_data = {}
            if meta_content:
                try:
                    # utf-8-sig 兼容带 BOM 的元数据文件
                    meta_data = json.loads(meta_content.decode('utf-8-sig'))
                except Exception as parse_err:
                    logging.warning(f"[Chisa DLC] ⚠️ Chisa_DLC_Metadata.json 解析失败: {parse_err}")
                    
            if not meta_data:
                # 拉取/解析失败: 本地若已有真实元数据(非占位)则原样保留，避免一次网络抖动导致永久的占位数据
                existing = {}
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, 'r', encoding='utf-8-sig') as mf:
                            existing = json.load(mf)
                    except Exception:
                        existing = {}
                if existing and not existing.get("is_placeholder"):
                    meta_data = existing
                    logging.warning("[Chisa DLC] ⚠️ 本次元数据拉取失败，已保留本地历史元数据。")
                else:
                    if store_type == "custom":
                        meta_data = {
                            "store_name": f"{owner} 的创意工坊",
                            "author": owner,
                            "description": f"来自 {repo_name} 仓库的第三方内容",
                            "is_placeholder": True
                        }
                    else:
                        meta_data = {
                            "store_name": "千小妹官方云仓",
                            "author": "千小妹",
                            "description": "官方精选推荐内容",
                            "is_official": True,
                            "is_placeholder": True
                        }
                    logging.warning("[Chisa DLC] ⚠️ 元数据不可用且无历史数据，本次使用占位元数据。")
                    
            with open(meta_path, 'w', encoding='utf-8') as mf:
                json.dump(meta_data, mf, ensure_ascii=False)
                
            # Download banner: try meta_data.banner_url first, then candidate paths
            banner_dir = self._get_banner_dir()
            os.makedirs(banner_dir, exist_ok=True)
            if store_type == "official":
                banner_local_path = os.path.join(banner_dir, "shop_banner.jpg")
            else:
                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(repo_id))
                banner_local_path = os.path.join(banner_dir, f"workshop_{safe_id}.jpg")
            
            banner_content = None
            # Priority 1: banner_url from metadata (must be GitHub raw)
            banner_url = meta_data.get("banner_url", "")
            if banner_url and banner_url.startswith("https://raw.githubusercontent.com/"):
                b_url = banner_url
                if node and node != "direct":
                    b_url = f"https://{node}/{banner_url}"
                banner_content = await _do_fetch(b_url, node)
                if banner_content is None and node and node != "direct":
                    banner_content = await _do_fetch(banner_url, "direct")
                if banner_content is None:
                    # banner_url 的 jsDelivr 变体 (把 owner/repo 后的路径拼到 jsDelivr 源上)
                    m_b = re.search(r"raw\.githubusercontent\.com/([^/]+)/([^/]+)/(?:refs/heads/)?(.+)", banner_url)
                    if m_b:
                        js_url = f"https://cdn.jsdelivr.net/gh/{m_b.group(1)}/{m_b.group(2)}@{m_b.group(3)}"
                        banner_content = await _do_fetch(js_url, "direct")
            
            # Priority 2: candidate paths in repo (走多源兜底)
            if not banner_content:
                candidates = ["assets/banner.png", "assets/banner.jpg", "assets/banner.gif", "assets/banner.webp", "banner.png", "banner.jpg", "banner.gif", "banner.webp"]
                for cand in candidates:
                    banner_content, _ = await fetch_repo_file(cand)
                    if banner_content:
                        break
                    
            if banner_content:
                with open(banner_local_path, 'wb') as bf:
                    bf.write(banner_content)
                    
            # 记录最近一次成功连接的工坊仓库，供前端在 localStorage 不可用 (sandbox) 时恢复状态
            if store_type == "custom" and repo_id:
                try:
                    last_repo_path = os.path.join(self._get_banner_dir(), "..", "Workshop", "_last_repo.json")
                    last_repo_path = os.path.abspath(last_repo_path)
                    os.makedirs(os.path.dirname(last_repo_path), exist_ok=True)
                    with open(last_repo_path, 'w', encoding='utf-8') as lf:
                        json.dump({"url": custom_url, "repo_id": repo_id, "store_name": meta_data.get("store_name", "")}, lf, ensure_ascii=False)
                except Exception as persist_err:
                    logging.warning(f"[Chisa DLC] ⚠️ 写入 last_repo 失败: {persist_err}")
                    
            return jsonify({"status": "success", "metadata": meta_data})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_get_last_custom_repo(self):
        """读取最近一次成功连接的工坊仓库 (sandbox 下 localStorage 不可用时的状态恢复通道)"""
        try:
            import os
            import json
            from quart import jsonify
            last_repo_path = os.path.abspath(os.path.join(self._get_banner_dir(), "..", "Workshop", "_last_repo.json"))
            if os.path.exists(last_repo_path):
                try:
                    with open(last_repo_path, 'r', encoding='utf-8-sig') as f:
                        data = json.load(f)
                    if data and data.get("repo_id"):
                        return jsonify({"status": "success", "data": data})
                except Exception:
                    pass
            return jsonify({"status": "missing"}) # v4.1.4 修复: 避免触发前端异常捕获
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    def _get_workshop_bookmarks_path(self):
        import os
        return os.path.abspath(os.path.join(self._get_banner_dir(), "..", "Workshop", "_bookmarks.json"))

    async def page_get_workshop_bookmarks(self):
        """读取工坊书架 (sandbox 下 localStorage 不可用，书架改由后端持久化)"""
        try:
            import os
            import json
            from quart import jsonify
            path = self._get_workshop_bookmarks_path()
            bookmarks = []
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8-sig') as f:
                        bookmarks = json.load(f)
                except Exception:
                    bookmarks = []
            if not isinstance(bookmarks, list):
                bookmarks = []
            return jsonify({"status": "success", "data": bookmarks})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_save_workshop_bookmarks(self):
        """保存工坊书架 (全量覆盖写)"""
        try:
            import os
            import json
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            bookmarks = payload.get("bookmarks", [])
            if not isinstance(bookmarks, list):
                return jsonify({"status": "error", "message": "Invalid bookmarks"}), 400
            # 清洗: 只保留 url/name 字段，url 必须为字符串且长度受限
            cleaned = []
            for b in bookmarks[:20]:
                if isinstance(b, dict):
                    url = str(b.get("url", "")).strip()[:300]
                    name = str(b.get("name", ""))[:80]
                    if url:
                        cleaned.append({"url": url, "name": name})
                elif isinstance(b, str) and b.strip():
                    cleaned.append({"url": b.strip()[:300], "name": ""})
            path = self._get_workshop_bookmarks_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cleaned, f, ensure_ascii=False, indent=2)
            return jsonify({"status": "success", "data": cleaned})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_dlc_metadata(self):
        """读取指定商店的本地缓存元数据 (前端 SDK 响应形态不确定时的元数据专用获取通道)"""
        try:
            import os
            import json
            from quart import jsonify, request
            store_type = request.args.get("store_type", "official")
            repo_id = request.args.get("repo_id", "")
            if store_type == "custom" and not repo_id.strip():
                return jsonify({"status": "missing"})
            index_dir = self._get_store_dir(store_type, repo_id)
            meta_path = os.path.join(index_dir, "metadata.json")
            if not os.path.exists(meta_path):
                return jsonify({"status": "missing"})
            try:
                with open(meta_path, 'r', encoding='utf-8-sig') as f:
                    meta_data = json.load(f)
            except Exception:
                return jsonify({"status": "missing"})
            return jsonify({"status": "success", "data": meta_data})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    # ---------- v4.0.08 皮肤商店: 索引/配置拉取与校验 ----------
    OFFICIAL_SKIN_SOURCE = "dddada123/astrbot_plugin_chisa_still_eating_photo"

    def _skins_dir(self):
        import os
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        try:
            base_data_path = get_astrbot_data_path()
        except ImportError:
            base_data_path = "data"
        d = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "skins"))
        os.makedirs(d, exist_ok=True)
        return d

    BUILTIN_SKIN_IDS = {
        "maple_dew", "yy_xuanling", "chisa_red_black", "chisa_red_white",
    }
    SKIN_ASSET_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

    def _normalize_skin_source(self, value):
        """Return canonical owner/repo for a GitHub source, or None."""
        if not isinstance(value, str):
            return None
        text = value.strip().rstrip("/")
        if not text:
            return None
        url_match = re.fullmatch(
            r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?",
            text,
            re.IGNORECASE,
        )
        pair_match = re.fullmatch(
            r"([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?",
            text,
            re.IGNORECASE,
        )
        match = url_match or pair_match
        if not match:
            return None
        owner, repo_name = match.group(1), match.group(2)
        if owner in (".", "..") or repo_name in (".", ".."):
            return None
        return f"{owner.lower()}/{repo_name.lower()}"

    def _skin_custom_sources(self):
        import json
        sources = []
        src_path = os.path.join(self._skins_dir(), "_sources.json")
        if not os.path.exists(src_path):
            return sources
        try:
            with open(src_path, "r", encoding="utf-8-sig") as f:
                raw_sources = json.load(f)
        except Exception:
            return sources
        if not isinstance(raw_sources, list):
            return sources
        for raw_source in raw_sources:
            source = self._normalize_skin_source(raw_source)
            if source and source != self.OFFICIAL_SKIN_SOURCE and source not in sources:
                sources.append(source)
        return sources

    def _skin_source_allowed(self, source):
        return source == self.OFFICIAL_SKIN_SOURCE or source in self._skin_custom_sources()

    def _skin_pref_path(self):
        return os.path.join(self._skins_dir(), "_skin_pref.json")

    def _skin_store_dir(self, source):
        """Return the isolated local store directory for one skin source."""
        source = self._normalize_skin_source(source) or self.OFFICIAL_SKIN_SOURCE
        if source == self.OFFICIAL_SKIN_SOURCE:
            folder = "OfficialWS"
        else:
            owner, repo_name = source.split("/", 1)
            folder = f"{owner}_{repo_name}"
        store_dir = os.path.join(self._skins_dir(), folder)
        os.makedirs(store_dir, exist_ok=True)
        return store_dir

    def _skin_source_index_path(self, source):
        return os.path.join(self._skin_store_dir(source), "skin", "index.json")

    def _skin_config_path(self, skin_id, source=None):
        source = self._normalize_skin_source(source) if source else None
        if source:
            return os.path.join(self._skin_store_dir(source), "skin", f"{skin_id}.json")
        return os.path.join(self._skins_dir(), f"{skin_id}.json")

    def _skin_asset_cache_dir(self, skin_id, source):
        return os.path.join(self._skin_store_dir(source), "skin")

    def _safe_skin_asset_rel(self, value):
        if not isinstance(value, str):
            return None
        rel = value.strip()
        if ".." in rel or "\\" in rel:
            return None
        if not re.fullmatch(r"skin/[A-Za-z0-9][A-Za-z0-9_.-]{0,110}", rel):
            return None
        if os.path.splitext(rel)[1].lower() not in self.SKIN_ASSET_EXTENSIONS:
            return None
        return rel

    def _atomic_write_json(self, path, data):
        import json
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.tmp.{os.getpid()}.{id(data)}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _load_cached_skin(self, skin_id, expected_source=None):
        import json
        expected = self._normalize_skin_source(expected_source) if expected_source else None
        sources = [expected] if expected else [self.OFFICIAL_SKIN_SOURCE] + self._skin_custom_sources()
        paths = [(source, self._skin_config_path(skin_id, source)) for source in sources if source]
        # Read the pre-4.1.94 flat cache once so existing installations migrate.
        paths.append((None, self._skin_config_path(skin_id)))
        for path_source, path in paths:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                cleaned, err = self._validate_skin_json(data)
                if err or cleaned.get("id") != skin_id:
                    continue
                source = self._normalize_skin_source(data.get("_source")) or path_source or self.OFFICIAL_SKIN_SOURCE
                if expected and source != expected:
                    continue
                cleaned["_source"] = source
                cleaned["_official"] = source == self.OFFICIAL_SKIN_SOURCE
                target_path = self._skin_config_path(skin_id, source)
                if path != target_path or data != cleaned:
                    self._atomic_write_json(target_path, cleaned)
                    if path != target_path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                return cleaned
            except Exception:
                continue
        return None

    def _write_cached_skin(self, cleaned, source):
        source = self._normalize_skin_source(source) or self.OFFICIAL_SKIN_SOURCE
        cached = dict(cleaned)
        cached["_source"] = source
        cached["_official"] = source == self.OFFICIAL_SKIN_SOURCE
        self._atomic_write_json(self._skin_config_path(cached["id"], source), cached)
        return cached

    SKIN_VAR_WHITELIST = {
        "--hover-tint", "--bg", "--panel", "--card", "--text", "--muted",
        "--primary", "--primary-hover", "--primary-contrast", "--line", "--shadow",
        "--surface", "--surface-dark", "--input-bg", "--overlay",
    }
    COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{6}|rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*,\s*(0|1|0?\.\d+)\s*\))$")

    def _skin_is_glass(self, data):
        if not isinstance(data, dict):
            return False
        type_value = str(data.get("type", data.get("skin_type", data.get("theme_type", ""))) or "").strip().lower()
        glass_value = data.get("glass")
        glass_flag = glass_value is True or str(glass_value).strip().lower() in ("1", "true", "yes", "glass", "frosted", "毛玻璃")
        return type_value in ("glass", "frosted", "frosted-glass", "transparent", "毛玻璃") or glass_flag

    def _validate_skin_json(self, data):
        """校验第三方皮肤 JSON: 键白名单 + 颜色格式。返回 (clean_data, err_msg)"""
        import re as _re
        if not isinstance(data, dict):
            return None, "皮肤配置必须是 JSON 对象"
        if data.get("schema_version") != 1:
            return None, "schema_version 必须为 1"
        sid = str(data.get("id", "")).strip()
        if not sid or len(sid) > 40 or not _re.fullmatch(r"[a-z0-9_]+", sid):
            return None, "id 必须为 1-40 位小写字母/数字/下划线"
        vars_in = data.get("vars")
        if not isinstance(vars_in, dict) or not vars_in:
            return None, "vars 不能为空"
        clean_vars = {}
        for k, v in vars_in.items():
            if k not in self.SKIN_VAR_WHITELIST:
                continue  # 白名单外键直接丢弃 (防注入)
            if not isinstance(v, str) or not self.COLOR_RE.match(v.strip()):
                return None, f"变量 {k} 的颜色格式不合法"
            clean_vars[k] = v.strip()
        if "--text" not in clean_vars or "--bg" not in clean_vars:
            return None, "vars 至少需要包含 --text 与 --bg"
        is_glass = self._skin_is_glass(data)
        cleaned = {
            "schema_version": 1,
            "id": sid,
            "name": str(data.get("name", sid))[:40],
            "author": str(data.get("author", ""))[:40],
            "type": "glass" if is_glass else "solid",
            "desc": str(data.get("desc", ""))[:100],
            "vars": clean_vars,
            "glass": is_glass,
            "_skin_type_version": 1,
            "is_custom": True,
        }
        q = data.get("quotes")
        if isinstance(q, list):
            cleaned["quotes"] = [str(x)[:80] for x in q[:6] if str(x).strip()]
        assets = data.get("assets") if isinstance(data.get("assets"), dict) else {}
        bg = assets.get("bg") or data.get("bg") or data.get("background")
        if isinstance(bg, str) and bg.strip():
            rel = self._safe_skin_asset_rel(bg)
            if not rel:
                return None, "assets.bg 必须是 skin/ 下的安全图片路径"
            cleaned["assets"] = {"bg": rel}
        return cleaned, None

    async def _skin_fetch_raw(self, repo, rel_path, preferred_node=None):
        """Fetch one validated skin file using the selected node then fallbacks."""
        import aiohttp
        import json as _json
        from urllib.parse import quote

        repo = self._normalize_skin_source(repo)
        safe_config = re.fullmatch(r"skin/[a-z0-9_]{1,40}\.json", str(rel_path or ""))
        if not repo or not (rel_path == "skin/index.json" or safe_config or self._safe_skin_asset_rel(rel_path)):
            return None

        timeout = aiohttp.ClientTimeout(total=25)

        async def _do_fetch(url, trust_env):
            try:
                async with aiohttp.ClientSession(trust_env=trust_env) as session:
                    async with session.get(url, timeout=timeout, headers={"Accept": "application/octet-stream"}) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            if content:
                                return content
                        logging.warning(f"[Chisa Skin] GET {url} -> HTTP {resp.status}")
            except Exception as exc:
                logging.warning(f"[Chisa Skin] GET {url} failed: {exc}")
            return None

        # The kitchen uploader writes to repo.default_branch. Discover and cache it,
        # then retain main/master as compatibility fallbacks when the API is unavailable.
        branch_cache = getattr(self, "_skin_branch_cache", None)
        if branch_cache is None:
            branch_cache = {}
            self._skin_branch_cache = branch_cache
        branch = branch_cache.get(repo)
        if not branch:
            api_url = f"https://api.github.com/repos/{repo}"
            try:
                async with aiohttp.ClientSession(trust_env=True) as session:
                    async with session.get(api_url, timeout=timeout, headers={"Accept": "application/vnd.github+json"}) as resp:
                        if resp.status == 200:
                            info = _json.loads((await resp.read()).decode("utf-8"))
                            candidate = str(info.get("default_branch", "")).strip()
                            if candidate and ".." not in candidate and re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", candidate):
                                branch = candidate
            except Exception as exc:
                logging.warning(f"[Chisa Skin] default branch lookup failed for {repo}: {exc}")
        branch = branch or "main"
        branch_cache[repo] = branch
        branches = []
        for candidate in (branch, "main", "master"):
            if candidate not in branches:
                branches.append(candidate)

        preferred = str(preferred_node or "").strip().lower()
        if preferred == "smart":
            try:
                preferred = str(await self._get_optimal_dlc_node() or "direct").strip().lower()
            except Exception:
                preferred = "direct"
        if preferred not in ("direct", "") and not re.fullmatch(r"[a-z0-9.-]{1,120}", preferred):
            preferred = "direct"
        mirror_nodes = ["gh-proxy.com", "hk.gh-proxy.com", "gh.dpik.top", "edgeone.gh-proxy.com"]
        if preferred not in ("direct", "") and preferred not in mirror_nodes:
            mirror_nodes.insert(0, preferred)

        # Honor the user's selected acceleration node first. Direct GitHub then
        # remains a proxy-aware fallback, followed by CDN and other mirrors.
        for ref in branches:
            encoded_ref = quote(ref, safe="/")
            raw_url = f"https://raw.githubusercontent.com/{repo}/{encoded_ref}/{rel_path}"
            if preferred not in ("direct", ""):
                content = await _do_fetch(f"https://{preferred}/{raw_url}", False)
                if content:
                    return content
            content = await _do_fetch(raw_url, True)
            if content:
                return content
            content = await _do_fetch(f"https://cdn.jsdelivr.net/gh/{repo}@{encoded_ref}/{rel_path}", True)
            if content:
                return content
            for node in mirror_nodes:
                if node == preferred:
                    continue
                content = await _do_fetch(f"https://{node}/{raw_url}", False)
                if content:
                    return content
        return None

    async def page_skin_index(self):
        """按 official/custom/all 模式拉取并合并已授权皮肤源索引。"""
        try:
            import json
            from quart import jsonify, request

            mode = str(request.args.get("mode", "all")).strip().lower()
            if mode not in ("official", "custom", "all"):
                return jsonify({"status": "error", "message": "Invalid skin index mode"}), 400

            requested_raw = request.args.get("source", "")
            preferred_node = str(request.args.get("node", "") or "").strip()
            requested = self._normalize_skin_source(requested_raw) if requested_raw else None
            if requested_raw and not requested:
                return jsonify({"status": "error", "message": "Invalid skin source"}), 400

            custom_sources = self._skin_custom_sources()
            if mode == "official":
                if requested and requested != self.OFFICIAL_SKIN_SOURCE:
                    return jsonify({"status": "error", "message": "Source is not official"}), 403
                sources = [self.OFFICIAL_SKIN_SOURCE]
            elif mode == "custom":
                if requested:
                    if requested == self.OFFICIAL_SKIN_SOURCE or requested not in custom_sources:
                        return jsonify({"status": "error", "message": "Custom skin source is not subscribed"}), 403
                    sources = [requested]
                else:
                    sources = custom_sources
            else:
                if requested:
                    if not self._skin_source_allowed(requested):
                        return jsonify({"status": "error", "message": "Skin source is not subscribed"}), 403
                    sources = [requested]
                else:
                    sources = [self.OFFICIAL_SKIN_SOURCE] + custom_sources

            merged = []
            for repo in sources:
                raw = await self._skin_fetch_raw(repo, "skin/index.json", preferred_node)
                if not raw:
                    continue
                try:
                    data = json.loads(raw.decode("utf-8-sig"))
                    if not isinstance(data, dict) or data.get("schema_version") != 1:
                        continue
                    items = data.get("skins", [])
                    if not isinstance(items, list):
                        continue
                except Exception:
                    continue
                try:
                    self._atomic_write_json(self._skin_source_index_path(repo), data)
                except Exception as exc:
                    logging.warning(f"[Chisa Skin] 保存皮肤索引失败: {repo}: {exc}")

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    skin_id = str(item.get("id", "")).strip()
                    if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                        continue
                    if skin_id in self.BUILTIN_SKIN_IDS and repo != self.OFFICIAL_SKIN_SOURCE:
                        continue
                    config_path = str(item.get("config", f"skin/{skin_id}.json")).strip()
                    if config_path != f"skin/{skin_id}.json":
                        continue
                    item_assets = item.get("assets") if isinstance(item.get("assets"), dict) else {}
                    bg_path = item.get("bg") or item_assets.get("bg")
                    if bg_path is not None:
                        bg_path = self._safe_skin_asset_rel(bg_path)
                        if not bg_path:
                            continue

                    entry = {
                        "id": skin_id,
                        "name": str(item.get("name", skin_id))[:40],
                        "author": str(item.get("author", ""))[:40],
                        "config": config_path,
                        "glass": self._skin_is_glass(item),
                        "_source": repo,
                        "_official": repo == self.OFFICIAL_SKIN_SOURCE,
                        "_installed": skin_id in self.BUILTIN_SKIN_IDS or self._load_cached_skin(skin_id, repo) is not None,
                    }
                    if bg_path:
                        entry["bg"] = bg_path
                    merged.append(entry)

            if mode == "all" and not requested:
                try:
                    self._atomic_write_json(os.path.join(self._skins_dir(), "_index_cache.json"), merged)
                except Exception:
                    pass

            return jsonify({"status": "success", "data": merged, "sources": sources, "mode": mode})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def _get_or_fetch_skin_config(self, skin_id, source, force=False, preferred_node=None):
        import json
        if not force:
            cached = self._load_cached_skin(skin_id, source)
            if cached and cached.get("_skin_type_version") == 1:
                return cached, None
            # 4.1.92 caches may contain a false solid type; revalidate them once.
            if cached:
                logging.info(f"[Chisa Skin] 重新校验旧皮肤类型缓存: {source}/{skin_id}")

        raw = await self._skin_fetch_raw(source, f"skin/{skin_id}.json", preferred_node)
        if not raw:
            return None, "皮肤配置拉取失败"
        try:
            data = json.loads(raw.decode("utf-8-sig"))
        except Exception:
            return None, "皮肤配置不是有效 JSON"
        cleaned, err = self._validate_skin_json(data)
        if err:
            return None, f"皮肤配置校验失败: {err}"
        if cleaned.get("id") != skin_id:
            return None, "皮肤配置 id 与请求不一致"
        return self._write_cached_skin(cleaned, source), None

    async def page_skin_get(self):
        """从已授权源读取皮肤配置，本地有效缓存优先。"""
        try:
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            skin_id = str(payload.get("id", "")).strip()
            if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                return jsonify({"status": "error", "message": "Invalid skin id"}), 400

            source_raw = payload.get("source", "") or self.OFFICIAL_SKIN_SOURCE
            source = self._normalize_skin_source(source_raw)
            if not source:
                return jsonify({"status": "error", "message": "Invalid skin source"}), 400
            if skin_id in self.BUILTIN_SKIN_IDS and source != self.OFFICIAL_SKIN_SOURCE:
                return jsonify({"status": "error", "message": "Built-in skin source must be official"}), 403

            cached = self._load_cached_skin(skin_id, source)
            source_subscribed = self._skin_source_allowed(source)
            if not source_subscribed:
                if not cached:
                    return jsonify({"status": "error", "message": "未订阅该皮肤源且无有效本地缓存"}), 403
                return jsonify({"status": "success", "data": cached})

            force = str(payload.get("force", "")).lower() in ("1", "true") or payload.get("force") is True
            preferred_node = str(payload.get("node", "") or "").strip()
            config, err = await self._get_or_fetch_skin_config(skin_id, source, force, preferred_node)
            if err:
                return jsonify({"status": "error", "message": err}), 502 if err == "皮肤配置拉取失败" else 400
            return jsonify({"status": "success", "data": config})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_skin_local(self):
        """列出按来源隔离保存的本地皮肤配置，并兼容旧版平铺缓存。"""
        try:
            import json
            from quart import jsonify
            root = self._skins_dir()
            candidates = []
            known_sources = [self.OFFICIAL_SKIN_SOURCE] + self._skin_custom_sources()
            for source in known_sources:
                skin_dir = os.path.join(self._skin_store_dir(source), "skin")
                if not os.path.isdir(skin_dir):
                    continue
                for filename in os.listdir(skin_dir):
                    if filename == "index.json" or not filename.endswith(".json"):
                        continue
                    if re.fullmatch(r"[a-z0-9_]{1,40}\.json", filename):
                        candidates.append((filename[:-5], source, os.path.join(skin_dir, filename)))
            for folder in os.listdir(root):
                folder_path = os.path.join(root, folder)
                if not os.path.isdir(folder_path) or folder.startswith("_"):
                    continue
                skin_dir = os.path.join(folder_path, "skin")
                if not os.path.isdir(skin_dir):
                    continue
                for filename in os.listdir(skin_dir):
                    if filename == "index.json" or not re.fullmatch(r"[a-z0-9_]{1,40}\.json", filename):
                        continue
                    path = os.path.join(skin_dir, filename)
                    try:
                        with open(path, "r", encoding="utf-8-sig") as f:
                            raw = json.load(f)
                        source = self._normalize_skin_source(raw.get("_source")) if isinstance(raw, dict) else None
                    except Exception:
                        source = None
                    if source and (filename[:-5], source, path) not in candidates:
                        candidates.append((filename[:-5], source, path))

            result = []
            seen = set()
            for skin_id, source, _ in candidates:
                key = (skin_id, source)
                if key in seen:
                    continue
                seen.add(key)
                cached = self._load_cached_skin(skin_id, source)
                if cached:
                    cached["_installed"] = True
                    result.append(cached)

            # Legacy root configs may not contain _source; retain them once.
            for filename in os.listdir(root):
                if filename.startswith("_") or not re.fullmatch(r"[a-z0-9_]{1,40}\.json", filename):
                    continue
                skin_id = filename[:-5]
                cached = self._load_cached_skin(skin_id)
                if cached and (skin_id, cached.get("_source")) not in seen:
                    cached["_installed"] = True
                    result.append(cached)
            result.sort(key=lambda item: (item.get("name", ""), item.get("id", ""), item.get("_source", "")))
            return jsonify({"status": "success", "data": result})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_skin_delete(self):
        """删除未激活的指定来源皮肤配置和背景，不影响其他来源同名皮肤。"""
        try:
            import json
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            skin_id = str(payload.get("id", "")).strip()
            if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                return jsonify({"status": "error", "message": "Invalid skin id"}), 400
            if skin_id in self.BUILTIN_SKIN_IDS:
                return jsonify({"status": "error", "message": "Built-in skin cannot be deleted"}), 403

            requested_raw = payload.get("source", "")
            if not requested_raw:
                return jsonify({"status": "error", "message": "Skin source is required for deletion"}), 400
            requested_source = self._normalize_skin_source(requested_raw)
            if not requested_source:
                return jsonify({"status": "error", "message": "Invalid skin source"}), 400
            cached = self._load_cached_skin(skin_id, requested_source)
            source = requested_source
            if not source:
                return jsonify({"status": "missing", "id": skin_id})
            if cached and cached.get("_source") != source:
                return jsonify({"status": "error", "message": "Cached skin source mismatch"}), 409

            pref_path = self._skin_pref_path()
            if os.path.exists(pref_path):
                try:
                    with open(pref_path, "r", encoding="utf-8-sig") as f:
                        pref = json.load(f)
                    pref_source = self._normalize_skin_source(pref.get("source")) if isinstance(pref, dict) else None
                    if isinstance(pref, dict) and pref.get("skin_id") == skin_id and (not pref_source or pref_source == source):
                        return jsonify({"status": "error", "message": "Active preferred skin cannot be deleted"}), 409
                except Exception:
                    pass

            config_path = self._skin_config_path(skin_id, source)
            skin_dir = self._skin_asset_cache_dir(skin_id, source)
            asset_name = None
            if cached and isinstance(cached.get("assets"), dict):
                asset_name = os.path.basename(str(cached["assets"].get("bg", "")))
            asset_path = os.path.join(skin_dir, asset_name) if asset_name else ""
            legacy_asset_root = os.path.join(self._skins_dir(), "_assets", skin_id)
            legacy_source_dir = os.path.join(legacy_asset_root, hashlib.sha256(source.encode("utf-8")).hexdigest()[:16])
            existed = os.path.exists(config_path) or (asset_path and os.path.exists(asset_path)) or os.path.isdir(legacy_source_dir)
            if os.path.exists(config_path):
                os.remove(config_path)
            if asset_path and os.path.exists(asset_path):
                os.remove(asset_path)
            if os.path.isdir(legacy_source_dir):
                shutil.rmtree(legacy_source_dir)
            if os.path.isdir(legacy_asset_root) and not os.listdir(legacy_asset_root):
                os.rmdir(legacy_asset_root)
            if not existed:
                return jsonify({"status": "missing", "data": {"id": skin_id, "source": source, "deleted": False}})
            return jsonify({"status": "success", "data": {"id": skin_id, "source": source, "deleted": True}})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_skin_sources(self):
        """读取规范化订阅源；官方源固定存在且不可移除。"""
        try:
            from quart import jsonify
            sources = [self.OFFICIAL_SKIN_SOURCE] + self._skin_custom_sources()
            return jsonify({"status": "success", "data": sources})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_save_skin_sources(self):
        """保存最多五个规范化社区源；官方源固定且不可移除。"""
        try:
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            raw_sources = payload.get("sources", [])
            if not isinstance(raw_sources, list):
                return jsonify({"status": "error", "message": "Invalid sources"}), 400

            custom_sources = []
            for raw_source in raw_sources:
                source = self._normalize_skin_source(raw_source)
                if not source:
                    return jsonify({"status": "error", "message": f"Invalid GitHub skin source: {raw_source}"}), 400
                if source == self.OFFICIAL_SKIN_SOURCE:
                    continue
                if source not in custom_sources:
                    custom_sources.append(source)
                if len(custom_sources) >= 5:
                    break

            self._atomic_write_json(os.path.join(self._skins_dir(), "_sources.json"), custom_sources)
            return jsonify({"status": "success", "data": [self.OFFICIAL_SKIN_SOURCE] + custom_sources})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    # 皮肤资源注册表: 文件名 -> 图库仓库相对路径 (v4.0.03, 资源托管于 astrbot_plugin_chisa_still_eating_photo 仓库 skin/ 目录)
    SKIN_ASSETS = {
        "03.jpg": "skin/03.jpg",
        "04.jpg": "skin/04.jpg",
    }
    BUILTIN_SKIN_ASSETS = {
        "maple_dew": "03.jpg",
        "yy_xuanling": "04.jpg",
    }
    SKIN_ASSET_CHUNK_BYTES = 192 * 1024

    def _skin_asset_descriptor(self, local_path, response_skin_id, source, cached):
        import mimetypes
        size = os.path.getsize(local_path)
        chunk_size = self.SKIN_ASSET_CHUNK_BYTES
        return {
            "id": response_skin_id,
            "skin_id": response_skin_id,
            "source": source,
            "file": os.path.basename(local_path),
            "mime": mimetypes.guess_type(local_path)[0] or "application/octet-stream",
            "size": size,
            "chunk_size": chunk_size,
            "chunk_count": (size + chunk_size - 1) // chunk_size,
            "delivery": "chunked",
            "cached": bool(cached),
        }

    async def page_skin_asset(self):
        """本地缓存优先下发内置或来源明确的动态皮肤背景。"""
        try:
            from quart import jsonify, request

            payload_file = str(request.args.get("file", "")).strip()
            skin_id = str(request.args.get("skin_id", "")).strip()
            force = str(request.args.get("force", "")).lower() in ("1", "true")
            preferred_node = str(request.args.get("node", "") or "").strip()

            if not skin_id or skin_id in self.BUILTIN_SKIN_ASSETS:
                expected_file = self.BUILTIN_SKIN_ASSETS.get(skin_id, payload_file)
                if expected_file not in self.SKIN_ASSETS:
                    return jsonify({"status": "error", "message": "Unknown built-in skin asset"}), 404
                if payload_file and payload_file != expected_file:
                    return jsonify({"status": "error", "message": "Built-in skin asset mismatch"}), 400
                payload_file = expected_file
                source = self.OFFICIAL_SKIN_SOURCE
                rel_path = self.SKIN_ASSETS[payload_file]
                local_path = os.path.join(self._skins_dir(), payload_file)
                response_skin_id = skin_id or None
            else:
                if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                    return jsonify({"status": "error", "message": "Invalid skin id"}), 400

                cached_any_source = self._load_cached_skin(skin_id)
                source_raw = request.args.get("source", "")
                if source_raw:
                    source = self._normalize_skin_source(source_raw)
                elif cached_any_source:
                    source = cached_any_source.get("_source")
                else:
                    source = self.OFFICIAL_SKIN_SOURCE
                if not source:
                    return jsonify({"status": "error", "message": "Invalid skin source"}), 400
                if skin_id in self.BUILTIN_SKIN_IDS and source != self.OFFICIAL_SKIN_SOURCE:
                    return jsonify({"status": "error", "message": "Built-in skin source must be official"}), 403

                config = self._load_cached_skin(skin_id, source)
                if not config:
                    if not self._skin_source_allowed(source):
                        return jsonify({"status": "error", "message": "Skin source is not subscribed and has no valid local cache"}), 403
                    config, err = await self._get_or_fetch_skin_config(skin_id, source, False, preferred_node)
                    if err:
                        return jsonify({"status": "error", "message": err}), 502 if err == "皮肤配置拉取失败" else 400
                rel_path = self._safe_skin_asset_rel((config.get("assets") or {}).get("bg"))
                if not rel_path:
                    return jsonify({"status": "error", "message": "Skin has no valid background asset"}), 404

                asset_name = os.path.basename(rel_path)
                if payload_file and payload_file not in (asset_name, rel_path):
                    return jsonify({"status": "error", "message": "Skin asset does not match cached config"}), 400
                cache_dir = self._skin_asset_cache_dir(skin_id, source)
                os.makedirs(cache_dir, exist_ok=True)
                local_path = os.path.join(cache_dir, asset_name)
                legacy_path = os.path.join(
                    self._skins_dir(), "_assets", skin_id,
                    hashlib.sha256(source.encode("utf-8")).hexdigest()[:16], asset_name,
                )
                if not force and not os.path.exists(local_path) and os.path.exists(legacy_path):
                    try:
                        shutil.copy2(legacy_path, local_path)
                        logging.info(f"[Chisa Skin] 迁移旧背景缓存: {legacy_path} -> {local_path}")
                    except OSError as exc:
                        logging.warning(f"[Chisa Skin] 旧背景缓存迁移失败: {exc}")
                response_skin_id = skin_id

            if not force and os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                return jsonify({
                    "status": "success",
                    "data": self._skin_asset_descriptor(local_path, response_skin_id, source, True),
                })

            logging.info(f"[Chisa Skin] 开始下载背景: {source}/{rel_path} node={preferred_node or 'direct'} force={force}")
            content = await self._skin_fetch_raw(source, rel_path, preferred_node)
            if not content:
                logging.warning(f"[Chisa Skin] 皮肤资源拉取失败: {source}/{rel_path}")
                return jsonify({"status": "error", "message": "Skin asset download failed"}), 502

            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            temp_path = f"{local_path}.tmp.{os.getpid()}.{id(content)}"
            try:
                with open(temp_path, "wb") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, local_path)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

            logging.info(f"[Chisa Skin] 皮肤资源已缓存: {source}/{rel_path} ({len(content)} bytes)")
            return jsonify({
                "status": "success",
                "data": self._skin_asset_descriptor(local_path, response_skin_id, source, False),
            })
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_skin_asset_chunk(self):
        """读取已缓存背景的一小段，避免大图 base64 撞到 WebUI bridge 消息限制。"""
        try:
            import base64
            from quart import jsonify, request

            payload_file = str(request.args.get("file", "")).strip()
            skin_id = str(request.args.get("skin_id", "")).strip()
            try:
                chunk_index = int(request.args.get("index", "-1"))
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": "Invalid skin asset chunk index"}), 400

            if not skin_id or skin_id in self.BUILTIN_SKIN_ASSETS:
                expected_file = self.BUILTIN_SKIN_ASSETS.get(skin_id, payload_file)
                if expected_file not in self.SKIN_ASSETS:
                    return jsonify({"status": "error", "message": "Unknown built-in skin asset"}), 404
                if payload_file and payload_file != expected_file:
                    return jsonify({"status": "error", "message": "Built-in skin asset mismatch"}), 400
                source = self.OFFICIAL_SKIN_SOURCE
                local_path = os.path.join(self._skins_dir(), expected_file)
                response_skin_id = skin_id or None
            else:
                if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                    return jsonify({"status": "error", "message": "Invalid skin id"}), 400
                source_raw = request.args.get("source", "")
                if source_raw:
                    source = self._normalize_skin_source(source_raw)
                else:
                    cached_any_source = self._load_cached_skin(skin_id)
                    source = cached_any_source.get("_source") if cached_any_source else None
                if not source:
                    return jsonify({"status": "error", "message": "Invalid skin source"}), 400
                config = self._load_cached_skin(skin_id, source)
                if not config:
                    return jsonify({"status": "error", "message": "Skin config is not cached"}), 409
                rel_path = self._safe_skin_asset_rel((config.get("assets") or {}).get("bg"))
                if not rel_path:
                    return jsonify({"status": "error", "message": "Skin has no valid background asset"}), 404
                asset_name = os.path.basename(rel_path)
                if payload_file and payload_file not in (asset_name, rel_path):
                    return jsonify({"status": "error", "message": "Skin asset does not match cached config"}), 400
                local_path = os.path.join(self._skin_asset_cache_dir(skin_id, source), asset_name)
                response_skin_id = skin_id

            if not os.path.isfile(local_path) or os.path.getsize(local_path) <= 0:
                return jsonify({"status": "error", "message": "Skin asset is not cached; call skin_asset first"}), 409
            size = os.path.getsize(local_path)
            chunk_size = self.SKIN_ASSET_CHUNK_BYTES
            chunk_count = (size + chunk_size - 1) // chunk_size
            if chunk_index < 0 or chunk_index >= chunk_count:
                return jsonify({"status": "error", "message": "Skin asset chunk index out of range"}), 416
            with open(local_path, "rb") as stream:
                stream.seek(chunk_index * chunk_size)
                raw_chunk = stream.read(chunk_size)
            return jsonify({
                "status": "success",
                "data": {
                    "id": response_skin_id,
                    "skin_id": response_skin_id,
                    "source": source,
                    "index": chunk_index,
                    "chunk_count": chunk_count,
                    "chunk": base64.b64encode(raw_chunk).decode("ascii"),
                },
            })
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_get_skin_pref(self):
        """读取皮肤偏好，并为旧格式补齐规范化 source。"""
        try:
            import json
            from quart import jsonify
            pref_path = self._skin_pref_path()
            if not os.path.exists(pref_path):
                return jsonify({"status": "missing"})
            try:
                with open(pref_path, "r", encoding="utf-8-sig") as f:
                    raw_pref = json.load(f)
            except Exception:
                return jsonify({"status": "missing"})

            skin_id = str(raw_pref.get("skin_id", "")).strip() if isinstance(raw_pref, dict) else ""
            if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                return jsonify({"status": "missing"})
            try:
                bg_blur = max(0, min(100, int(raw_pref.get("bg_blur", 0))))
            except Exception:
                bg_blur = 0

            source = self._normalize_skin_source(raw_pref.get("source", ""))
            if skin_id in self.BUILTIN_SKIN_IDS:
                source = self.OFFICIAL_SKIN_SOURCE
            elif not source:
                cached = self._load_cached_skin(skin_id)
                source = cached.get("_source") if cached else self.OFFICIAL_SKIN_SOURCE
            pref = {"skin_id": skin_id, "source": source, "bg_blur": bg_blur}
            if raw_pref != pref:
                self._atomic_write_json(pref_path, pref)
            logging.info(f"[Chisa Skin] 读取皮肤偏好: {skin_id} source={source} blur={bg_blur}")
            return jsonify({"status": "success", "data": pref})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_save_skin_pref(self):
        """保存包含皮肤 ID、来源和毛玻璃力度的偏好。"""
        try:
            from quart import jsonify, request
            payload = await request.get_json(silent=True) or {}
            skin_id = str(payload.get("skin_id", "")).strip()
            if not re.fullmatch(r"[a-z0-9_]{1,40}", skin_id):
                return jsonify({"status": "error", "message": "Invalid skin id"}), 400
            try:
                bg_blur = max(0, min(100, int(payload.get("bg_blur", 0))))
            except Exception:
                bg_blur = 0

            source_raw = payload.get("source", "")
            source = self._normalize_skin_source(source_raw) if source_raw else None
            if source_raw and not source:
                return jsonify({"status": "error", "message": "Invalid skin source"}), 400
            if skin_id in self.BUILTIN_SKIN_IDS:
                if source and source != self.OFFICIAL_SKIN_SOURCE:
                    return jsonify({"status": "error", "message": "Built-in skin source must be official"}), 400
                source = self.OFFICIAL_SKIN_SOURCE
            elif not source:
                cached = self._load_cached_skin(skin_id)
                source = cached.get("_source") if cached else self.OFFICIAL_SKIN_SOURCE
            if not self._skin_source_allowed(source) and not self._load_cached_skin(skin_id, source):
                return jsonify({"status": "error", "message": "Skin source is not subscribed and has no valid local cache"}), 403

            pref = {"skin_id": skin_id, "source": source, "bg_blur": bg_blur}
            self._atomic_write_json(self._skin_pref_path(), pref)
            logging.info(f"[Chisa Skin] 皮肤偏好已保存: {skin_id} source={source} blur={bg_blur}")
            # Keep this endpoint on the bridge-native ok/data contract. Some
            # bridge versions unwrap data before returning it to JavaScript.
            return jsonify({"status": "ok", "data": {"saved": True, "preference": pref}})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_store_banner(self):
        try:
            import os
            import mimetypes
            import base64
            from quart import request, jsonify
            store_type = request.args.get("store_type", "official")
            repo_id = request.args.get("repo_id", "")
            
            banner_dir = self._get_banner_dir()
            if store_type == "official":
                path = os.path.join(banner_dir, "shop_banner.jpg")
            else:
                safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(repo_id))
                path = os.path.join(banner_dir, f"workshop_{safe_id}.jpg")
                
            if os.path.exists(path) and os.path.isfile(path):
                media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
                with open(path, "rb") as f:
                    raw_bytes = f.read()
                    data_url = f"data:{media_type};base64,{base64.b64encode(raw_bytes).decode('ascii')}"
                return jsonify({"status": "success", "data_url": data_url})
            else:
                return jsonify({"status": "missing"}) # v4.1.4 修复: 避免触发前端异常捕获
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    def _get_cover_dir(self, store_type, repo_id=None):
        """封面缓存目录: 官方走 Shop/cover，工坊按仓库隔离到 Workshop/cover/{repo_id}/，防止同名封面互相覆盖"""
        import os
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
        try:
            base_data_path = get_astrbot_data_path()
        except ImportError:
            base_data_path = "data"
        pic_root = os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC")
        if store_type == "custom" and repo_id:
            safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(repo_id))
            return os.path.abspath(os.path.join(pic_root, "Workshop", "cover", safe_id))
        return os.path.abspath(os.path.join(pic_root, "Shop", "cover"))

    async def page_fetch_single_cover(self):
        try:
            import os
            import aiohttp
            from quart import request, jsonify
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            
            payload = await request.get_json(silent=True) or {}
            filename = payload.get("file", "").strip()
            node = payload.get("node", "smart")
            custom_url = payload.get("custom_url", "").strip()
            store_type = payload.get("store_type", "official")
            repo_id = payload.get("repo_id", "")
            
            if not filename or ".." in filename or "/" in filename or "\\" in filename:
                return jsonify({"status": "error"}), 400
                
            raw_base = "https://raw.githubusercontent.com/dddada123/astrbot_plugin_chisa_still_eating_photo/main"
            if custom_url:
                import re as _re
                m_cover = _re.search(r"github\.com[/:]([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/|$)", custom_url)
                if m_cover:
                    raw_base = f"https://raw.githubusercontent.com/{m_cover.group(1)}/{m_cover.group(2)}/main"
                    
            original_url = f"{raw_base}/covers/{filename}"
            
            if node == "smart":
                node = await self._get_optimal_dlc_node()
                
            url = original_url
            if node and node != "direct":
                url = f"https://{node}/{original_url}"
                
            try:
                async with aiohttp.ClientSession(trust_env=(node == "direct")) as session:
                    async with session.get(url, timeout=15) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                        content = await resp.read()
            except Exception as e:
                import logging
                if payload.get("node", "smart") == "smart":
                    logging.warning(f"[Chisa DLC] ⚠️ 锁定节点单张图拉取失败 ({e})，清除测速缓存！")
                    self._dlc_best_node = None
                    return jsonify({"status": "error", "message": "ALL_NODES_FAILED"}), 500
                return jsonify({"status": "error"}), 500
                    
            cover_dir = self._get_cover_dir(store_type, repo_id)
            os.makedirs(cover_dir, exist_ok=True)
            full_path = os.path.join(cover_dir, filename)
            
            with open(full_path, 'wb') as f:
                f.write(content)
                
            return jsonify({"status": "success"})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error"}), 500

    
    
    async def page_get_dlc_downloaded(self):
        try:
            import os
            import json
            from quart import jsonify, request
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            
            try:
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            # 与下载记录写入端对称: 官方读 Shop/index，工坊读 Workshop/{repo_id}/index
            store_type = request.args.get("store_type", "official")
            repo_id = request.args.get("repo_id", "").strip()
            if store_type == "custom" and repo_id:
                safe_rid = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_id)
                json_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "Workshop", safe_rid, "index", "downloaded.json"))
            else:
                json_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "Shop", "index", "downloaded.json"))
            
            downloaded = []
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8-sig") as f:
                    downloaded = json.load(f)
                    
            return jsonify({"status": "success", "data": downloaded})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    
    async def page_get_download_progress(self):
        try:
            import os
            from quart import jsonify, request
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            
            payload = await request.get_json(silent=True) or {}
            dlc_id = payload.get("id", "").strip()
            
            if not dlc_id or ".." in dlc_id or "/" in dlc_id or "\\" in dlc_id:
                return jsonify({"status": "error"}), 400
                
            try:
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            temp_zip_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", f"temp_{dlc_id}.zip"))
            
            if os.path.exists(temp_zip_path):
                size = os.path.getsize(temp_zip_path)
                return jsonify({"status": "success", "size": size})
            else:
                return jsonify({"status": "success", "size": 0})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_download_dlc(self):
        try:
            import os
            import aiohttp
            import hashlib
            import shutil
            import zipfile
            import logging
            from quart import jsonify, request
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            
            payload = await request.get_json(silent=True) or {}
            dlc_id = payload.get("id", "").strip()
            expected_sha256 = payload.get("sha256", "").strip()
            node = payload.get("node", "smart")
            store_type = payload.get("store_type", "official")
            custom_url = payload.get("custom_url", "").strip()
            
            if not dlc_id or ".." in dlc_id or "/" in dlc_id or "\\" in dlc_id:
                return jsonify({"status": "error", "message": "Invalid DLC ID"}), 400
                
            # Release 下载基址: 官方走主仓库; 工坊按用户仓库构建 (Release Tag 约定与官方一致: Chisa_Dlc_Store)
            if store_type == "custom" and custom_url:
                import re as _re
                m_repo = _re.search(r"github\.com[/:]([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/|$)", custom_url)
                if not m_repo:
                    return jsonify({"status": "error", "message": "无法识别第三方仓库地址"}), 400
                release_base = f"https://github.com/{m_repo.group(1)}/{m_repo.group(2)}/releases/download/Chisa_Dlc_Store"
                logging.info(f"[Chisa DLC] 🏪 工坊下载通道: {release_base}/{dlc_id}.zip")
            else:
                release_base = "https://github.com/dddada123/astrbot_plugin_chisa_still_eating_photo/releases/download/Chisa_Dlc_Store"
            original_url = f"{release_base}/{dlc_id}.zip"
            
            if node == "smart":
                node = await self._get_optimal_dlc_node()
                
            url = original_url
            if node and node != "direct":
                url = f"https://{node}/{original_url}"
                
            try:
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            temp_zip_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", f"temp_{dlc_id}.zip"))
            
            logging.info(f"[Chisa DLC] 开始下载 DLC 包: {url}")
            try:
                async with aiohttp.ClientSession(trust_env=(node == "direct")) as session:
                    async with session.get(url, timeout=300) as resp:
                        if resp.status != 200:
                            raise Exception(f"HTTP {resp.status}")
                            
                        # Streaming download
                        sha256_hash = hashlib.sha256()
                        with open(temp_zip_path, 'wb') as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                f.write(chunk)
                                sha256_hash.update(chunk)
                                
                        actual_sha256 = sha256_hash.hexdigest()
            except Exception as e:
                import logging
                if payload.get("node", "smart") == "smart":
                    logging.warning(f"[Chisa DLC] ⚠️ 锁定节点下载大包失败 ({e})，清除测速缓存！")
                    self._dlc_best_node = None
                    return jsonify({"status": "error", "message": "ALL_NODES_FAILED"}), 500
                return jsonify({"status": "error", "message": str(e)}), 500
                
            # Hash verification
            if expected_sha256 and actual_sha256 != expected_sha256:
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
                return jsonify({"status": "error", "message": f"Hash mismatch! Expected {expected_sha256[:8]}, got {actual_sha256[:8]}"}), 500
                
            # Extraction
            target_extract_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            try:
                import asyncio
                
                def extract_safe(z_path, t_dir):
                    with zipfile.ZipFile(z_path, 'r') as z_ref:
                        for z_info in z_ref.filelist:
                            if ".." in z_info.filename or z_info.filename.startswith("/") or z_info.filename.startswith("\\"):
                                raise Exception("Unsafe path in ZIP")
                        z_ref.extractall(t_dir)
                
                # Offload heavy IO to a separate thread so it doesn't block the main asyncio loop
                await asyncio.to_thread(extract_safe, temp_zip_path, target_extract_dir)
                    
                # Clean up
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
                    
                logging.info(f"[Chisa DLC] 🎉 DLC {dlc_id} 部署完成！")
                
                # Record download: 官方记到 Shop/index，工坊记到 Workshop/{repo_id}/index，互不混写
                import json
                repo_id_param = payload.get("repo_id", "").strip()
                if store_type == "custom" and repo_id_param:
                    safe_rid = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo_id_param)
                    json_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "Workshop", safe_rid, "index", "downloaded.json"))
                else:
                    json_path = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating", "Webui-PIC", "Shop", "index", "downloaded.json"))
                os.makedirs(os.path.dirname(json_path), exist_ok=True)
                downloaded = []
                if os.path.exists(json_path):
                    try:
                        with open(json_path, "r", encoding="utf-8-sig") as f:
                            downloaded = json.load(f)
                    except:
                        pass
                if dlc_id not in downloaded:
                    downloaded.append(dlc_id)
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(downloaded, f, ensure_ascii=False)
                        
                # Reload caches (async wrapper or direct call)
                self._reload_all_caches()
                
                return jsonify({"status": "success"})
            except Exception as e:
                return jsonify({"status": "error", "message": f"Extraction failed: {str(e)}"}), 500
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error", "message": str(e)}), 500

    async def page_dlc_cover(self):
        try:
            import os
            import mimetypes
            import base64
            from quart import request, jsonify
            
            filename = request.args.get("file", "")
            store_type = request.args.get("store_type", "official")
            repo_id = request.args.get("repo_id", "")
            if not filename or ".." in filename or "/" in filename or "\\" in filename:
                return jsonify({"status": "error"}), 400
                
            cover_dir = self._get_cover_dir(store_type, repo_id)
            full_path = os.path.join(cover_dir, filename)
            
            if not os.path.exists(full_path) or not os.path.isfile(full_path):
                return jsonify({"status": "missing"}) # v4.1.4 修复: 避免触发前端异常捕获
                
            media_type = mimetypes.guess_type(full_path)[0] or "image/jpeg"
            with open(full_path, "rb") as f:
                raw_bytes = f.read()
                data_url = f"data:{media_type};base64,{base64.b64encode(raw_bytes).decode('ascii')}"
                
            return jsonify({"status": "success", "data_url": data_url})
        except Exception as e:
            from quart import jsonify
            return jsonify({"status": "error"}), 500

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
            
            if not name or ".." in name or "/" in name or "\\" in name:
                return jsonify({"status": "error", "message": "干饭人名字为空或包含非法字符"}), 400
                
            try:
                from astrbot.core.utils.astrbot_path import get_astrbot_data_path
                base_data_path = get_astrbot_data_path()
            except ImportError:
                base_data_path = "data"
                
            base_dir = os.path.abspath(os.path.join(base_data_path, "plugin_data", "astrbot_plugin_chisa_still_eating"))
            gf_dir = os.path.abspath(os.path.join(base_dir, "ganfanren", name))
            if not gf_dir.startswith(os.path.abspath(os.path.join(base_dir, "ganfanren"))): return jsonify({"status": "error", "message": "非法越权访问"}), 403
            os.makedirs(gf_dir, exist_ok=True)
            
            words_path = os.path.join(gf_dir, "words.txt")
            with open(words_path, "w", encoding="utf-8") as f:
                f.write(words)
                
            for img in images:
                fname = img.get("filename", "")
                if ".." in fname or "/" in fname or "\\" in fname: continue
                b64 = img.get("data", "")
                if fname and b64:
                    if b64.startswith("data:"):
                        b64 = b64.split(",")[1]
                    img_path = os.path.abspath(os.path.join(gf_dir, fname))
                    if not img_path.startswith(os.path.abspath(gf_dir)): continue
                    with open(img_path, "wb") as f:
                        f.write(base64.b64decode(b64))
                        
            self._reload_all_caches()
            return jsonify({"status": "ok", "message": f"成功招募干饭人 {name}！"}), 200
        except Exception as e:
            import traceback
            logging.error(f"[ChisaEating] page_add_ganfanren error: {traceback.format_exc()}")
            return jsonify({"status": "error", "message": str(e)}), 500

