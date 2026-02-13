import aiohttp
from typing import Optional, Dict, Any, List
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
        self.base_url = "http://localhost:8080"
        self._session: Optional[aiohttp.ClientSession] = None

    async def initialize(self):
        """初始化时创建持久化的 HTTP 会话"""
        self._session = aiohttp.ClientSession()

    async def terminate(self):
        """终止时关闭会话"""
        if self._session:
            await self._session.close()

    # ==========================================================
    # 工具方法
    # ==========================================================

    async def _fetch_json(self, url: str, params: Optional[Dict] = None) -> Optional[Any]:
        """统一的 HTTP GET 请求方法，返回 JSON 数据"""
        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"HTTP 请求失败: {url}, 状态码: {resp.status}")
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"HTTP 请求异常: {url}, 错误: {e}")
            return None

    def _extract_first_item(self, data: Any) -> Optional[Dict]:
        """从响应数据中提取第一个有效项"""
        if isinstance(data, list) and data:
            return data[0]
        elif isinstance(data, dict):
            return data
        return None

    async def _fetch_oss_url(self, oss_id: str) -> Optional[tuple[str, str]]:
        """获取 OSS 文件的真实 URL 和原始文件名

        Returns:
            tuple[url, original_name] 或 None
        """
        url = f"{self.base_url}/resource/oss/web/listByIds/{oss_id}"
        oss_json = await self._fetch_json(url)

        if not oss_json or oss_json.get("code") != 200:
            return None

        oss_data = oss_json.get("data", [])
        if not oss_data:
            return None

        real_url = oss_data[0].get("url")
        original_name = oss_data[0].get("originalName", "未命名文件")

        return (real_url, original_name) if real_url else None

    def _format_search_result(self, item: Dict) -> str:
        """格式化单条搜索结果"""
        cid = item.get("code") or item.get("id")
        title = item.get("title", "无标题")
        file_type = item.get("fileType", "DEFAULT")
        emoji = EMOJI_MAP.get(file_type, EMOJI_MAP["DEFAULT"])
        return f" {emoji}【{cid}】{title}"

    # ==========================================================
    # 指令：/搜瓜 [关键词]
    # ==========================================================

    @filter.command("搜瓜")
    async def search_melon(self, event: AstrMessageEvent):
        """搜索资源：/搜瓜 <关键词>"""
        # 解析关键词
        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            yield event.plain_result("❌ 请输入搜索关键词，例如：/搜瓜 demo")
            return

        keyword = parts[1].strip()

        # 请求搜索接口
        url = f"{self.base_url}/media/mediaData/web/list"
        params = {"contentText": keyword, "status": "enable"}

        data = await self._fetch_json(url, params)

        if data is None:
            yield event.plain_result(f"❌ 搜索接口请求失败，请稍后重试")
            return

        if not data:
            yield event.plain_result(f"🔍 搜索【{keyword}】，未查到相关信息")
            return

        # 构建结果消息
        count = len(data)
        msg_lines = [f"🔍 搜索【{keyword}】，共查到 {count} 条信息：\n"]
        msg_lines.extend(self._format_search_result(item) for item in data)
        msg_lines.append("\n💡 输入 /cid [CODE] 获取详情")
        msg_lines.append("🔑 如需解压密码请查看公告")

        yield event.plain_result("\n".join(msg_lines))

    # ==========================================================
    # 指令：/cid [CODE]
    # ==========================================================

    @filter.command("cid")
    async def query_detail(self, event: AstrMessageEvent):
        """获取资源详情：/cid <CODE>"""
        # 解析 CODE 参数
        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            yield event.plain_result("❌ 请输入 Code，例如：/cid 2001")
            return

        cid_arg = parts[1].strip()
        yield event.plain_result(f"⏳ 正在查询 {cid_arg}，请稍等...")

        # 查询详情
        query_url = f"{self.base_url}/media/mediaData/web/query"
        raw_data = await self._fetch_json(query_url, params={"code": cid_arg})

        if raw_data is None:
            yield event.plain_result("❌ 详情接口请求失败")
            return

        data = self._extract_first_item(raw_data)
        if not data:
            yield event.plain_result(f"❌ 未找到 Code 为 {cid_arg} 的资源")
            return

        # 构建消息链
        chain = await self._build_detail_chain(data, cid_arg)
        yield event.chain_result(chain)

    async def _build_detail_chain(self, data: Dict, cid_arg: str) -> List:
        """构建详情消息链"""
        chain = []

        # 基础信息
        title = data.get("title", "无标题")
        cover_url = data.get("coverUrl", "")
        file_type = data.get("fileType", "DEFAULT")
        netdisk_type = data.get("netdiskType", "未知网盘")
        netdisk_url = data.get("netdiskUrl", "")

        # 添加标题
        emoji = EMOJI_MAP.get(file_type, EMOJI_MAP["DEFAULT"])
        chain.append(Plain(f"{emoji} {title}\n"))

        # 添加封面
        if cover_url:
            chain.append(Image.fromURL(cover_url))

        # 根据文件类型添加内容
        if file_type == "IMAGE":
            await self._add_images(chain, data)
        elif file_type == "VIDEO":
            await self._add_videos(chain, data)
        elif file_type in ["ZIP", "PDF"]:
            await self._add_files(chain, data, cid_arg)
        else:
            chain.append(Plain("\n⚠️ 暂不支持该文件类型，请联系管理员"))

        # 添加网盘信息
        if netdisk_url:
            chain.append(Plain(f"\n📌 详情：【{netdisk_type}】\n🔗 {netdisk_url}"))

        return chain

    async def _add_images(self, chain: List, data: Dict):
        """添加图片到消息链"""
        images_str = data.get("imagesUrl", "")
        if images_str:
            img_urls = [url.strip() for url in images_str.split(",") if url.strip()]
            for url in img_urls:
                chain.append(Image.fromURL(url))

    async def _add_videos(self, chain: List, data: Dict):
        """添加视频到消息链"""
        video_urls = data.get("videoUrls", "")
        if not video_urls:
            chain.append(Plain("\n⚠️ 未找到视频资源"))
            return

        oss_ids = [i.strip() for i in video_urls.split(",") if i.strip()]
        for oss_id in oss_ids:
            result = await self._fetch_oss_url(oss_id)
            if result:
                real_url, _ = result
                chain.append(Video.fromURL(real_url))

    async def _add_files(self, chain: List, data: Dict, fallback_name: str):
        """添加文件到消息链"""
        file_urls = data.get("fileUrls", "")
        if not file_urls:
            chain.append(Plain("\n⚠️ 未找到文件资源"))
            return

        oss_ids = [i.strip() for i in file_urls.split(",") if i.strip()]
        for oss_id in oss_ids:
            result = await self._fetch_oss_url(oss_id)
            if result:
                real_url, original_name = result
                chain.append(File(url=real_url, name=original_name or fallback_name))