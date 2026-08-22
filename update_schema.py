import json
import os

path = r'D:\AI-Agent\千小妹还在吃\astrbot_plugin_chisa_still_eating-2.3.3\_conf_schema.json'

with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# Root level additions
data["generic_drink_templates"] = {
    "description": "🥤 常规无联动饮品推荐句式池",
    "hint": "抽中三次元普通饮品或未触发跨界时的后备饮品推荐池。可用变量: {bot}, {food}",
    "type": "list",
    "items": { "type": "string" },
    "default": [
        "铛铛！为你抽中了清爽的{food}！",
        "喝杯{food}解解渴吧！",
        "听{bot}的，今天来一杯{food}准没错~"
    ]
}

data["crossover_drink_templates"] = {
    "description": "🌀 跨次元大乱斗饮品联动句式池",
    "hint": "大乱斗模式下跨界抽中其他世界饮品时触发。",
    "type": "list",
    "items": { "type": "string" },
    "default": [
        "{bot_a}去{world_b}进货时，顺手带回了一杯{full_food_desc}！",
        "{bot_a}遇到了{bot_b}，一起畅饮了{full_food_desc}！"
    ]
}

data["dark_drink_templates"] = {
    "description": "☠️ 黑暗饮品专属全局句式池",
    "hint": "抽到黑暗饮品时触发。支持占位符: {bot}, {full_food_desc}",
    "type": "list",
    "items": { "type": "string" },
    "default": [
        "这杯{full_food_desc}真的能喝吗？！",
        "{bot}端着这杯冒着诡异气泡的{full_food_desc}，陷入了沉思..."
    ]
}

data["upload_common_food"] = {
    "description": "🍔 上传三次元食物图片",
    "hint": "在此上传三次元食物图片，系统会自动归档。",
    "type": "list",
    "items": { "type": "file" },
    "default": []
}

data["upload_common_drink"] = {
    "description": "🥤 上传三次元饮品图片",
    "hint": "在此上传三次元饮品图片，系统会自动归档。",
    "type": "list",
    "items": { "type": "file" },
    "default": []
}

# Add world specific additions
for world in ["world1", "world2", "world3", "world4"]:
    if world not in data: continue
    
    data[world]["items"]["11.专属饮品句式"] = {
        "description": "11.专属饮品句式",
        "hint": "本世界饮品普通推荐",
        "type": "list",
        "items": { "type": "string" },
        "default": [
            "这是{bot}为你推荐的饮品{food}，解解渴吧",
            "{bot}觉得这杯{food}最适合现在的你啦"
        ]
    }
    data[world]["items"]["12.厨师饮品句式"] = {
        "description": "12.厨师饮品句式",
        "hint": "【厨师】前缀饮品专属联动",
        "type": "list",
        "items": { "type": "string" },
        "default": [
            "哇！这可是【{chef}】特调的{food}哦，快尝尝",
            "【{chef}】端来了这杯{food}，看起来很不错呢"
        ]
    }
    data[world]["items"]["13.黑暗饮品句式"] = {
        "description": "13.黑暗饮品句式",
        "hint": "黑暗饮品惊恐文案",
        "type": "list",
        "items": { "type": "string" },
        "default": [
            "{bot}颤抖着递上这杯{full_food_desc}，它还在冒着诡异的泡泡..."
        ]
    }
    data[world]["items"]["14.上传食物图片"] = {
        "description": "14.上传食物图片",
        "hint": "在此上传当前世界的食物图片，系统会自动归档。",
        "type": "list",
        "items": { "type": "file" },
        "default": []
    }
    data[world]["items"]["15.上传饮品图片"] = {
        "description": "15.上传饮品图片",
        "hint": "在此上传当前世界的饮品图片，系统会自动归档。",
        "type": "list",
        "items": { "type": "file" },
        "default": []
    }
    data[world]["items"]["16.上传黑暗料理图片"] = {
        "description": "16.上传黑暗料理图片",
        "hint": "在此上传当前世界的黑暗料理图片，系统会自动归档。",
        "type": "list",
        "items": { "type": "file" },
        "default": []
    }

# Reorder root keys to make it look nice (put upload at bottom)
keys = list(data.keys())
# we can just dump it
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("Schema updated successfully!")









