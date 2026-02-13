import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Plain, Video, File
from astrbot.api import logger

# 文件类型对应的 Emoji 映射
EMOJI_MAP = {
    "IMAGE": "🖼️",
    "VIDEO": "📹",
    "PDF": "📄",
    "ZIP": "📦",
    "BOOK": "📚",
    "TEXT": "📝",
    "DEFAULT": "📁"
}

@register("astrbot_plugin_meta_collect", "yunus", "元采集平台搜索插件", "1.0.0")
class MelonSearchPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 基础接口地址
        self.base_url = "http://localhost:8080"

    # ==========================================================
    # 指令：/搜瓜 [关键词]
    # ==========================================================
    @filter.command("搜瓜")
    async def search_melon(self, event: AstrMessageEvent):
        """搜瓜 <关键词>"""
        # 1. 获取关键词
        parts = event.message_str.split(maxsplit=1)
        keyword = parts[1].strip() if len(parts) > 1 else ""

        if not keyword:
            yield event.plain_result("请输入搜索关键词，例如：/搜瓜 demo")
            return

        # 2. 准备接口请求
        url = f"{self.base_url}/media/mediaData/web/list"
        params = {
            "contentText": keyword,
            "status": "enable"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        yield event.plain_result(f"搜索接口请求失败，状态码: {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            logger.error(f"搜瓜接口异常: {e}")
            yield event.plain_result(f"连接接口时发生错误: {e}")
            return

        # 3. 处理返回数据
        if not data:
            yield event.plain_result(f"搜索【{keyword}】，未查到相关信息。")
            return

        # 获取结果数量
        count = len(data)

        # 4. 构建返回文本
        msg_lines = [
            f" 搜索【{keyword}】，共查到 {count} 条信息："
        ]

        for item in data:
            # ID 获取逻辑
            cid = item.get("code")
            if not cid:
                cid = item.get("id")

            title = item.get("title", "无标题")

            # 类型与Emoji处理
            file_type = item.get("fileType", "DEFAULT")
            emoji = EMOJI_MAP.get(file_type, EMOJI_MAP["DEFAULT"])

            # 格式：【ID】【Emoji 类型】【标题】
            msg_lines.append(f" {emoji}【{cid}】{title}")

        msg_lines.append("\n输入 /cid [CODE] 获取详情")
        msg_lines.append("如需解压密码请查看公告")

        # 发送文本结果
        yield event.plain_result("\n".join(msg_lines))

    # ==========================================================
    # 指令：/cid [CODE]
    # ==========================================================
    @filter.command("cid")
    async def query_detail(self, event: AstrMessageEvent):
        """cid <CODE> 获取详情"""

        # 1. 获取 ID 参数
        parts = event.message_str.split(maxsplit=1)
        cid_arg = parts[1].strip() if len(parts) > 1 else ""

        yield event.plain_result(f"正在查询{cid_arg}, 请稍等...")

        if not cid_arg:
            yield event.plain_result("请输入Code，例如：/cid 2001")
            return

        # 2. 准备接口请求
        query_url = f"{self.base_url}/media/mediaData/web/query"
        oss_url = f"{self.base_url}/resource/oss/web/listByIds"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(query_url, params={"code": cid_arg}) as resp:
                    if resp.status != 200:
                        yield event.plain_result("详情接口请求失败")
                        return
                    raw = await resp.json()

                # 数据解析兼容 (List 或 Dict)
                data = None
                if isinstance(raw, list) and raw:
                    data = raw[0]
                elif isinstance(raw, dict):
                    data = raw

                if not data:
                    yield event.plain_result("未找到对应的详情内容。")
                    return

                # 3. 提取基础字段
                title = data.get("title", "")
                cover_url = data.get("coverUrl", "")
                file_type = data.get("fileType", "DEFAULT")
                file_urls = data.get("fileUrls", "")
                video_urls = data.get("videoUrls", "")
                netdisk_type = data.get("netdiskType", "未知网盘")
                netdisk_url = data.get("netdiskUrl", "无链接")

                # 4. 构建图文消息链
                chain = []

                # --- 标题 ---
                chain.append(Plain(f"{title}\n"))

                # --- 封面主图 ---
                if cover_url:
                    chain.append(Image.fromURL(cover_url))

                # --- 根据类型展示额外媒体 ---

                # 处理 IMAGE 类型：展示多图
                if file_type == "IMAGE":
                    images_str = data.get("imagesUrl", "")
                    if images_str:
                        # 逗号分割，去除空白项
                        img_urls = [url.strip() for url in images_str.split(",") if url.strip()]
                        for url in img_urls:
                            chain.append(Image.fromURL(url))

                # 处理 VIDEO 类型：展示视频
                elif file_type == "VIDEO":
                    if not video_urls:
                        chain.append(Plain("\n(未找到资源ID)"))
                    else:
                        oss_ids = [i.strip() for i in video_urls.split(",") if i.strip()]
                        for oid in oss_ids:
                            async with session.get(f"{oss_url}/{oid}") as oss_resp:
                                if oss_resp.status != 200:
                                    continue

                                oss_json = await oss_resp.json()

                                if oss_json.get("code") != 200:
                                    continue

                                oss_data = oss_json.get("data", [])
                                if not oss_data:
                                    continue

                                real_url = oss_data[0].get("url")
                                if not real_url:
                                    continue

                                chain.append(Video.fromURL(real_url))

                elif file_type in ["ZIP", "PDF"]:
                    if not file_urls:
                        chain.append(Plain("\n(未找到资源ID)"))
                    else:
                        oss_ids = [i.strip() for i in file_urls.split(",") if i.strip()]
                        for oid in oss_ids:
                            async with session.get(f"{oss_url}/{oid}") as oss_resp:
                                if oss_resp.status != 200:
                                    continue

                                oss_json = await oss_resp.json()

                                if oss_json.get("code") != 200:
                                    continue

                                oss_data = oss_json.get("data", [])
                                if not oss_data:
                                    continue

                                real_url = oss_data[0].get("url")
                                original_name = oss_data[0].get("originalName", "cid_arg")
                                if not real_url:
                                    continue

                                chain.append(File(url=real_url, name=original_name))

                else:
                    chain.append(Plain("\n(暂不支持文件类型, 请联系管理员)"))

                # --- 网盘详情 ---
                if netdisk_url:
                    chain.append(Plain(f"\n详情：【{netdisk_type}】【{netdisk_url}】"))
        except Exception as e:
            logger.error(f"搜瓜详情接口异常: {e}")
            yield event.plain_result(f"获取详情失败: {e}")
            return

        yield event.chain_result(chain)

    async def initialize(self):
        pass

    async def terminate(self):
        pass