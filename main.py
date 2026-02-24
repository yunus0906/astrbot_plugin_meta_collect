import aiohttp
import os
import asyncio
import datetime
from typing import Optional, Dict, Any, List
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image, Plain, Video, File
from astrbot.api import logger
from astrbot.core.message.message_event_result import MessageChain

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
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.base_url = self.config.get("base_url", "http://localhost:8080")
        self._session: Optional[aiohttp.ClientSession] = None

        # 定时推送配置
        self.push_enabled = self.config.get("push_enabled", False)
        self.push_times = self.config.get("push_times", "08:00,12:00,17:00")
        self.push_check_hours = self.config.get("push_check_hours", 12)
        self.push_target_groups = self.config.get("push_target_groups", [])

        # 定时任务列表
        self._push_tasks = []

    async def initialize(self):
        """初始化时创建持久化的 HTTP 会话和启动定时任务"""
        self._session = aiohttp.ClientSession()

        # 启动定时推送任务
        if self.push_enabled and self.push_target_groups:
            for push_time in self._parse_push_times():
                task = asyncio.create_task(self.push_task(push_time))
                self._push_tasks.append(task)
            logger.info(f"[瓜推送] 已启动 {len(self._push_tasks)} 个定时推送任务")
        else:
            logger.info("[瓜推送] 定时推送功能未启用或未配置目标群组")

    async def terminate(self):
        """终止时关闭会话和取消定时任务"""
        # 取消所有定时任务
        for task in self._push_tasks:
            task.cancel()

        # 关闭会话
        if self._session:
            await self._session.close()

        logger.info("[瓜推送] 已停止所有定时任务和会话")

    def _parse_push_times(self) -> List[str]:
        """解析推送时间配置，返回时间列表"""
        times = self.push_times.split(",")
        return [t.strip() for t in times if t.strip()]

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

    async def _get_all_group_files(self, group_id: int, bot) -> List[Dict]:
        """
        获取群文档中的所有文件列表（递归获取所有文件夹）
        兼容现有的群文件获取实现

        Returns:
            包含文件信息的列表，每个元素为 dict，至少包含 'file_name' 和 'file_id'
        """
        try:
            from .src.file_ops import get_all_files_recursive_core
            all_files = await get_all_files_recursive_core(group_id, bot)
            logger.info(f"从群 {group_id} 获取到 {len(all_files)} 个群文档文件")
            return all_files
        except Exception as e:
            logger.warning(f"获取群文档列表失败: {e}")
            return []

    def _find_file_in_group(self, code: str, group_files: List[Dict]) -> Optional[Dict]:
        """
        在群文档列表中查找匹配的文件
        文件名规则：文件名（不含扩展名）与 code 完全一致

        Args:
            code: 要查找的 code
            group_files: 群文档文件列表

        Returns:
            匹配的文件信息 dict 或 None
        """
        if not group_files:
            return None

        for file_info in group_files:
            file_name = file_info.get('file_name', '')
            # 去除扩展名
            base_name, _ = os.path.splitext(file_name)

            # 文件名（不含扩展名）与 code 完全匹配
            if base_name == code:
                logger.info(f"在群文档中找到匹配文件: {file_name} (code: {code})")
                return file_info

        return None

    def _format_search_result(self, item: Dict) -> str:
        """格式化单条搜索结果"""
        cid = item.get("code") or item.get("id")
        title = item.get("title", "无标题")
        file_type = item.get("fileType", "DEFAULT")
        emoji = EMOJI_MAP.get(file_type, EMOJI_MAP["DEFAULT"])
        return f" {emoji}【{cid}】{title}"

    def _format_file_size(self, size_bytes: int) -> str:
        """格式化文件大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

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

        # 1. 尝试从群文档获取文件
        group_id_str = event.get_group_id()
        group_file = None

        if group_id_str and event.bot:
            try:
                group_id = int(group_id_str)
                logger.info(f"正在检查群 {group_id} 的文档...")
                group_files = await self._get_all_group_files(group_id, event.bot)
                group_file = self._find_file_in_group(cid_arg, group_files)

                if group_file:
                    logger.info(f"✅ 在群文档中找到文件，跳过网络请求")
                    # 直接返回群文档文件
                    chain = await self._build_group_file_chain(group_file, cid_arg)
                    yield event.chain_result(chain)
                    return
            except Exception as e:
                logger.warning(f"检查群文档时出错: {e}，继续使用网络查询")

        # 2. 群文档中未找到，查询详情接口
        query_url = f"{self.base_url}/media/mediaData/web/query"
        raw_data = await self._fetch_json(query_url, params={"code": cid_arg})

        if raw_data is None:
            yield event.plain_result("❌ 详情接口请求失败")
            return

        data = self._extract_first_item(raw_data)
        if not data:
            yield event.plain_result(f"❌ 未找到 Code 为 {cid_arg} 的资源")
            return

        # 3. 构建消息链（网络文件）
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

    async def _build_group_file_chain(self, group_file: Dict, code: str) -> List:
        """
        构建群文档文件的消息链

        Args:
            group_file: 群文档文件信息
            code: 文件 code
        """
        chain = []

        file_name = group_file.get('file_name', '未知文件')
        file_id = group_file.get('file_id', '')
        file_size = group_file.get('size', 0)
        parent_folder = group_file.get('parent_folder_name', '根目录')

        # 根据扩展名判断文件类型
        _, ext = os.path.splitext(file_name)
        ext_upper = ext.upper().lstrip('.')

        # 映射扩展名到 emoji
        emoji = EMOJI_MAP.get(ext_upper, EMOJI_MAP["DEFAULT"])

        # 格式化文件大小
        size_str = self._format_file_size(file_size)

        # 添加标题和信息
        text = (
            f"{emoji} 群文件内已存在: {file_name}\n"
            f"📂 所在文件夹：{parent_folder}\n"
            f"📦 文件大小：{size_str}\n"
            f"🔑 如需解压密码请查看公告"
        )

        chain.append(Plain(text))

        logger.info(f"从群文档返回文件: {file_name}, 大小: {size_str}")

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

    @filter.command("新瓜")
    async def check_updates(self, event: AstrMessageEvent, hours: int = None):
        """
        检查新瓜更新

        Args:
            hours: 检查最近多少小时，默认使用配置值
        """
        try:
            check_hours = hours or self.push_check_hours
            logger.info(f"[瓜推送] 手动检查最近 {check_hours} 小时的更新")

            melons = await self.fetch_recent_updates(check_hours)
            message_text = self.format_push_message(melons, check_hours)

            yield event.plain_result(message_text)
        except Exception as e:
            logger.error(f"[瓜推送] 检查更新时出错: {e}")
            yield event.plain_result(f"❌ 检查失败: {str(e)}")
        finally:
            event.stop_event()

    # ==========================================================
    # 定时推送功能
    # ==========================================================

    async def fetch_recent_updates(self, hours: int = 12) -> List[Dict]:
        """
        获取最近N小时更新的瓜

        Args:
            hours: 查询最近多少小时的更新

        Returns:
            瓜列表
        """
        try:
            # 计算时间范围
            now = datetime.datetime.now()
            start_time = now - datetime.timedelta(hours=12)

            params = {
                "updateTimeStart": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "updateTimeEnd": now.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "enable"
            }

            url = f"{self.base_url}/media/mediaData/web/list"
            # params = {
            #     "updateTime": update_time,
            #     "status": "enable"
            # }

            logger.info(f"[瓜推送] 查询最近 {hours} 小时的更新，时间戳: {start_time}")

            data = await self._fetch_json(url, params)

            if data is None:
                logger.error("[瓜推送] 接口请求失败")
                return []

            if not data:
                logger.info(f"[瓜推送] 最近 {hours} 小时没有新瓜")
                return []

            logger.info(f"[瓜推送] 找到 {len(data)} 个新瓜")
            return data

        except Exception as e:
            logger.error(f"[瓜推送] 获取新瓜时出错: {e}")
            return []

    def format_push_message(self, melons: List[Dict], hours: int) -> str:
        """
        格式化推送消息

        Args:
            melons: 瓜列表
            hours: 时间范围（小时）

        Returns:
            格式化后的消息文本
        """
        if not melons:
            return f"📢 最近 {hours} 小时没有新瓜更新"

        msg_lines = [
            f"🍉 新瓜速递 🍉",
            f"━━━━━━━━━━━━━━━",
            f"📊 最近 {hours} 小时更新了 {len(melons)} 个瓜：\n"
        ]

        for i, item in enumerate(melons, 1):
            cid = item.get("code") or item.get("id")
            title = item.get("title", "无标题")
            file_type = item.get("fileType", "DEFAULT")
            emoji = EMOJI_MAP.get(file_type, EMOJI_MAP["DEFAULT"])

            # 获取更新时间
            update_time = item.get("updateTime")
            time_str = ""
            if update_time:
                try:
                    dt = datetime.datetime.fromtimestamp(update_time / 1000)
                    time_str = dt.strftime("%m-%d %H:%M")
                except:
                    pass

            msg_lines.append(f"{i}. {emoji} [{cid}] {title}")
            if time_str:
                msg_lines.append(f"   ⏰ {time_str}")

        msg_lines.append("\n━━━━━━━━━━━━━━━")
        msg_lines.append("💡 输入 /cid [CODE] 查看详情")
        msg_lines.append("🔑 如需解压密码请查看公告")

        return "\n".join(msg_lines)

    async def send_push_to_groups(self):
        """向目标群组推送新瓜"""
        try:
            # 获取最近的瓜
            melons = await self.fetch_recent_updates(self.push_check_hours)

            if not self.push_target_groups:
                logger.info("[瓜推送] 未配置目标群组")
                return

            # 格式化消息
            message_text = self.format_push_message(melons, self.push_check_hours)

            logger.info(f"[瓜推送] 准备向 {len(self.push_target_groups)} 个群组推送")

            for group_id in self.push_target_groups:
                try:
                    message_chain = MessageChain()
                    message_chain.chain = [Plain(message_text)]

                    await self.context.send_message(str(group_id), message_chain)
                    logger.info(f"[瓜推送] 已向群 {group_id} 推送新瓜通知")

                    await asyncio.sleep(1)  # 避免发送过快
                except Exception as e:
                    logger.error(f"[瓜推送] 向群组 {group_id} 推送消息时出错: {e}")

        except Exception as e:
            logger.error(f"[瓜推送] 推送新瓜时出错: {e}")

    def calculate_sleep_time(self, target_time: str) -> float:
        """
        计算到下一次推送时间的秒数

        Args:
            target_time: 目标时间，格式如 "08:00"

        Returns:
            需要等待的秒数
        """
        now = datetime.datetime.now()
        hour, minute = map(int, target_time.split(":"))

        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)

        seconds = (target - now).total_seconds()
        return seconds

    async def push_task(self, push_time: str):
        """
        定时推送任务

        Args:
            push_time: 推送时间，格式如 "08:00"
        """
        logger.info(f"[瓜推送] 启动定时任务，推送时间: {push_time}")

        while True:
            try:
                # 计算到下次推送的时间
                sleep_time = self.calculate_sleep_time(push_time)
                logger.info(f"[瓜推送-{push_time}] 下次推送将在 {sleep_time / 3600:.2f} 小时后")

                # 等待到设定时间
                await asyncio.sleep(sleep_time)

                # 推送新瓜
                logger.info(f"[瓜推送-{push_time}] 开始执行推送")
                await self.send_push_to_groups()

                # 等待一段时间，避免重复推送
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                logger.info(f"[瓜推送-{push_time}] 定时任务已取消")
                break
            except Exception as e:
                logger.error(f"[瓜推送-{push_time}] 定时任务出错: {e}")
                await asyncio.sleep(300)

    @filter.command("gua_push_now")
    async def manual_push(self, event: AstrMessageEvent):
        """手动触发推送"""
        try:
            logger.info("[瓜推送] 手动触发推送")
            await self.send_push_to_groups()

            yield event.plain_result(
                f"✅ 已成功向 {len(self.push_target_groups)} 个群组推送新瓜通知"
            )
        except Exception as e:
            logger.error(f"[瓜推送] 手动推送时出错: {e}")
            yield event.plain_result(f"❌ 推送失败: {str(e)}")
        finally:
            event.stop_event()

    @filter.command("gua_push_status")
    async def check_push_status(self, event: AstrMessageEvent):
        """查看推送状态"""
        status_msg = [
            "🍉 瓜推送插件状态",
            "━━━━━━━━━━━━━━━"
        ]

        if self.push_enabled:
            status_msg.extend([
                f"✅ 状态: 已启用",
                f"📍 目标群组: {', '.join(map(str, self.push_target_groups))}",
                f"⏰ 推送时间: {self.push_times}",
                f"🕐 检查时长: 最近{self.push_check_hours}小时",
                f"📊 任务数量: {len(self._push_tasks)}个"
            ])

            # 计算每个任务的下次推送时间
            status_msg.append("\n⏰ 下次推送时间:")
            for push_time in self._parse_push_times():
                sleep_time = self.calculate_sleep_time(push_time)
                hours = int(sleep_time / 3600)
                minutes = int((sleep_time % 3600) / 60)
                status_msg.append(f"  • {push_time} - 还有{hours}小时{minutes}分钟")
        else:
            status_msg.append("❌ 状态: 未启用")

        yield event.plain_result("\n".join(status_msg))