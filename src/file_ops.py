"""
工具函数模块
用于提供群文档相关的辅助功能
"""
import os
from typing import List, Dict
from astrbot.api import logger


async def get_all_files_with_path(group_id: int, bot) -> List[Dict]:
    """
    递归获取所有文件，并计算其在备份目录中的相对路径。

    Args:
        group_id: 群号
        bot: bot 实例

    Returns:
        文件信息列表，每个元素包含文件的完整信息和相对路径
    """
    all_files = []
    # 结构: (folder_id, folder_name, relative_path)
    folders_to_scan = [(None, "根目录", "")]

    while folders_to_scan:
        current_folder_id, current_folder_name, current_relative_path = folders_to_scan.pop(0)

        try:
            # 使用 OneBot 协议的 call_action 方式
            if current_folder_id is None or current_folder_id == '/':
                result = await bot.api.call_action('get_group_root_files', group_id=group_id, file_count=2000)
            else:
                result = await bot.api.call_action('get_group_files_by_folder', group_id=group_id,
                                                   folder_id=current_folder_id, file_count=2000)

            if not result:
                continue

            # 处理文件
            if result.get('files'):
                for file_info in result['files']:
                    file_info['relative_path'] = os.path.join(current_relative_path, file_info.get('file_name', ''))
                    file_info['size'] = file_info.get('size', 0)  # 确保有 size 字段
                    file_info['parent_id'] = current_folder_id or '/'  # 保存父文件夹ID
                    all_files.append(file_info)

            # 处理文件夹
            if result.get('folders'):
                for folder in result['folders']:
                    if folder_id := folder.get('folder_id'):
                        new_relative_path = os.path.join(current_relative_path, folder.get('folder_name', ''))
                        folders_to_scan.append((folder_id, folder.get('folder_name', ''), new_relative_path))

        except Exception as e:
            logger.error(f"[{group_id}-群文件遍历] 递归获取文件夹 '{current_folder_name}' 内容时出错: {e}")
            continue

    return all_files


async def get_all_files_recursive_core(group_id: int, bot) -> List[Dict]:
    """
    递归获取所有文件，并补充父文件夹名称。
    兼容 /cdf, /cf, /sf, /df 等指令。

    Args:
        group_id: 群号
        bot: bot 实例

    Returns:
        文件信息列表，每个元素包含 parent_folder_name 字段
    """
    all_files_with_path = await get_all_files_with_path(group_id, bot)

    for file_info in all_files_with_path:
        path_parts = file_info.get('relative_path', '').split(os.path.sep)
        file_info['parent_folder_name'] = os.path.sep.join(path_parts[:-1]) if len(path_parts) > 1 else '根目录'

    return all_files_with_path