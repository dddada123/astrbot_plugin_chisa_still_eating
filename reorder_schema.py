import json
import os

path = r'D:\AI-Agent\千小妹还在吃\astrbot_plugin_chisa_still_eating\_conf_schema.json'

try:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if 'admin_users' in data:
        admin_data = data.pop('admin_users')
        new_data = {'admin_users': admin_data}
        new_data.update(data)
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(new_data, f, ensure_ascii=False, indent=2)
        print("Schema reordered successfully!")
except Exception as e:
    print(f"Error: {e}")






