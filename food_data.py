import os
import json
import random
from collections import deque

class FoodDataManager:
    def __init__(self, config):
        self.config = config
        self.data_dir = os.path.join("data", "plugin_data", "astrbot_plugin_chisa_still_eating")
        self.history_path = os.path.join(self.data_dir, "group_history.json")
        self.history_limit = self.config.get("history_limit", 30)
        self.group_history = {}
        self._load_history_cache()

    def _load_history_cache(self):
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for gid, lst in data.items():
                        self.group_history[gid] = deque(lst, maxlen=self.history_limit)
            except Exception:
                self.group_history = {}

    def _save_history_cache(self):
        try:
            export = {gid: list(deq) for gid, deq in self.group_history.items()}
            with open(self.history_path, "w", encoding="utf-8") as f:
                json.dump(export, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

    def filter_and_pick(self, group_id: str, full_pool: list, active_wv: str):
        if not full_pool: return None
        mode_loyal = self.config.get("mode_loyal", False)
        mode_roller = self.config.get("mode_roller", False)
        mode_normie = self.config.get("mode_normie", False)

        filtered_pool = []
        for item in full_pool:
            wv = item["wv"]
            if mode_normie:
                if wv == "common": filtered_pool.append(item)
                continue
            if mode_roller and wv == "common":
                continue
            if mode_loyal and wv != "common" and wv != active_wv:
                continue
            filtered_pool.append(item)

        if not filtered_pool: filtered_pool = full_pool

        # 动态捕捉 WebUI 最新的 history_limit 变化并平滑重构容量
        current_limit = self.config.get("history_limit", 30)
        if current_limit != self.history_limit:
            self.history_limit = current_limit
            for gid in list(self.group_history.keys()):
                self.group_history[gid] = deque(list(self.group_history[gid]), maxlen=self.history_limit)

        if group_id not in self.group_history:
            self.group_history[group_id] = deque(maxlen=self.history_limit)
        history = self.group_history[group_id]

        fresh_items = [i for i in filtered_pool if i["raw_name"] not in history]
        final_pool = fresh_items if fresh_items else filtered_pool
        
        # 按世界分组进行概率抽签
        world_groups = {}
        for item in final_pool:
            wv = item["wv"]
            if wv not in world_groups:
                world_groups[wv] = []
            world_groups[wv].append(item)
            
        available_worlds = list(world_groups.keys())
        
        # 权重映射
        weight_config = {
            "common": self.config.get("weight_3d", 70),
            "world1": self.config.get("weight_w1", 20),
            "world2": self.config.get("weight_w2", 5),
            "world3": self.config.get("weight_w3", 5),
            "world4": self.config.get("weight_w4", 0),
            "world5": self.config.get("weight_w5", 0)
        }
        
        # 计算有效权重
        weights = [weight_config.get(w, 10) for w in available_worlds]
        
        # 若所有可选项权重全为 0 或非法，降级为均等概率
        total_weight = sum(weights)
        if total_weight <= 0:
            weights = [1] * len(available_worlds)
            
        chosen_world = random.choices(available_worlds, weights=weights, k=1)[0]
        picked = random.choice(world_groups[chosen_world])

        # 仅在长度限制大于 0 时记录记忆
        if self.history_limit > 0:
            history.append(picked["raw_name"])
            self._save_history_cache()
            
        return picked

    def fetch_egg_text(self, char_name: str) -> str:
        vault = {
            "千咲": ["……但是被千咲吃光了！", "……千咲甚至连盘子都舔得发亮！"],
            "派蒙": ["……但是派蒙一不留神吃光了。", "……惹得派蒙在旁边心满意足地打了个饱嗝。"],
            "达妮娅": ["……达妮娅表示在残星会没吃过这么好的。", "……达妮娅顺手连锅带灶一起端回了残星会本部，并成为了人类。"]
        }
        pool = vault.get(char_name, [f"……但是被{char_name}吃光了。"])
        return random.choice(pool)








