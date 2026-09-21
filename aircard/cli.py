"""
Interactive CLI for AirCard Windows.
"""
from typing import Optional
import asyncio
import os
import sys
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn

from .config import find_apple_dll_dir
from .backup import latest_backup
from .device import get_first_device
from .scanner import load_saved_cards, save_cards, start_card_scan_session
from .image_util import prepare_card_skin
from .core_flasher import flash_card_skin, restore_original_card_async

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console(safe_box=True, legacy_windows=False)


def show_banner():
    console.clear()
    dll_dir = find_apple_dll_dir()
    dll_status = "[green]已检测到[/green]" if dll_dir else "[red]未找到（请安装 iTunes）[/red]"

    device = get_first_device()
    if device:
        dev_text = f"[green]已连接：[/green] {device.name}（[cyan]{device.product_type}[/cyan]，iOS {device.ios_version}）"
    else:
        dev_text = "[yellow]未连接（请通过 USB 连接并解锁 iPhone）[/yellow]"

    banner_text = (
        "[bold cyan]🎴 AirCard 卡面助手[/bold cyan]\n"
        "[dim]Windows 原生 Apple Wallet 卡面管理工具[/dim]\n\n"
        f"📱 [bold]iPhone：[/bold] {dev_text}\n"
        f"📦 [bold]Apple 移动设备支持：[/bold] {dll_status}"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def menu_scan_cards():
    console.print("\n[bold yellow]📡 Apple Wallet 卡片实时扫描[/bold yellow]")
    console.print("=" * 60)
    console.print("获取卡片哈希的方法：")
    console.print("  👉 [bold white]1.[/bold white] 双击 iPhone 侧边键或主屏幕按钮打开 Apple Pay。")
    console.print("  👉 [bold white]2.[/bold white] 使用面容 ID 或触控 ID 完成验证。")
    console.print("  👉 [bold white]3.[/bold white] 在屏幕上点选目标卡片。")
    console.print("\n[dim]扫描完成后按回车键或 Ctrl+C 停止。[/dim]")
    console.print("=" * 60 + "\n")

    stop_event = asyncio.Event()

    def on_card(card_hash: str, total_count: int):
        console.print(f"  ✨ [bold green]已发现卡片 [{total_count}]：[/bold green] [cyan]{card_hash}[/cyan]")
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    async def run_scan():
        task = asyncio.create_task(start_card_scan_session(on_card_found=on_card, stop_event=stop_event))
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, input, "正在扫描…按回车键停止：")
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            stop_event.set()
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    try:
        asyncio.run(run_scan())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print(f"\n[bold red]扫描错误：[/bold red] [yellow]{e}[/yellow]")
        console.print("[dim]请确认 iPhone 已连接、解锁，并已选择“信任此电脑”。[/dim]")

    cards = load_saved_cards()
    console.print(f"\n[green]✅ 扫描完成。已保存卡片：{len(cards)} 张[/green]")
    input("\n按回车键返回菜单…")


def menu_view_cards():
    cards = load_saved_cards()
    console.print(f"\n[bold]已保存的 Apple Wallet 卡片（{len(cards)}）：[/bold]")
    if not cards:
        console.print("[dim]尚未保存卡片。请使用选项 [1] 从 iPhone 扫描。[/dim]")
    else:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("卡片哈希（Pass 标识）", style="cyan")

        for idx, h in enumerate(cards, 1):
            table.add_row(str(idx), h)
        console.print(table)

    console.print("\n[1] 手动添加卡片哈希")
    console.print("[2] 删除一张卡片")
    console.print("[3] 清空全部卡片")
    console.print("[回车] 返回主菜单")

    choice = input("\n请选择：").strip()
    if choice == "1":
        manual = input("请输入卡片哈希：").strip()
        if len(manual) >= 20:
            cards.append(manual)
            save_cards(cards)
            console.print("[green]卡片已保存！[/green]")
    elif choice == "2":
        num = input("请输入要删除的卡片编号：").strip()
        try:
            idx = int(num) - 1
            if 0 <= idx < len(cards):
                removed = cards.pop(idx)
                save_cards(cards)
                console.print(f"[yellow]已移除 {removed}[/yellow]")
        except Exception:
            pass
    elif choice == "3":
        confirm = input("确定清空全部卡片吗？(y/N)：").strip().lower()
        if confirm == "y":
            save_cards([])
            console.print("[yellow]已清空全部已保存卡片。[/yellow]")


def menu_flash_skin():
    cards = load_saved_cards()
    if not cards:
        console.print("\n[red]没有可用卡片，请先使用选项 [1] 扫描。[/red]")
        input("\n按回车键返回菜单…")
        return

    console.print("\n[bold cyan]选择目标卡片：[/bold cyan]")
    for idx, h in enumerate(cards, 1):
        console.print(f"  [{idx}] {h}")

    card_choice = input(f"\n请输入卡片编号（1-{len(cards)}）或 all [1]：").strip()
    if not card_choice:
        card_choice = "1"

    selected_cards = []
    if card_choice.lower() == "all":
        selected_cards = cards
    else:
        try:
            idx = int(card_choice) - 1
            if 0 <= idx < len(cards):
                selected_cards = [cards[idx]]
            else:
                console.print("[red]选择无效。[/red]")
                return
        except ValueError:
            console.print("[red]选择无效。[/red]")
            return

    console.print("\n[bold cyan]选择卡面图片：[/bold cyan]")
    while True:
        img_path = input("将图片拖到此处（PNG/JPG/WebP），或输入路径：").strip().strip("'\"")
        if not img_path:
            return
        try:
            console.print("[dim]正在处理图片并转换为 1536 × 969 PNG…[/dim]")
            skin_bytes = prepare_card_skin(img_path)
            console.print(f"[green]✓ 图片已准备完成（{len(skin_bytes):,} 字节）[/green]\n")
            break
        except Exception as e:
            console.print(f"[red]图片处理失败：{e}。请换一张图片。[/red]")

    clean_choice = input("启用全图模式并隐藏银行 Logo？(y/N) [N]：").strip().lower()
    clean_logo = clean_choice in ("y", "yes", "1", "д", "да")

    for card_idx, target_card in enumerate(selected_cards, 1):
        console.print(f"[bold]正在更新卡片 [{card_idx}/{len(selected_cards)}]：[/bold] [cyan]{target_card}[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("正在连接…", total=7 if clean_logo else 3)

            def update_progress(step: int, total: int, msg: str):
                progress.update(task, completed=step, total=total, description=msg)

            try:
                success = flash_card_skin(
                    None,
                    target_card,
                    skin_bytes,
                    clean_logo=clean_logo,
                    progress_callback=update_progress,
                )
            except Exception as exc:
                success = False
                console.print(f"[bold red]更新失败：[/bold red] {exc}")

        if success:
            console.print(f"[bold green]🎉 成功：卡片 {target_card[:10]}… 已更新！[/bold green]")
        else:
            console.print(f"[bold red]❌ 失败：无法更新卡片 {target_card}。[/bold red]")

    console.print("\n" + "=" * 60)
    console.print("[bold green]全部完成！[/bold green]")
    console.print("👉 请强制关闭 iPhone 上的 [bold]Wallet[/bold]，然后重新打开查看新卡面。")
    console.print("=" * 60)
    input("\n按回车键返回菜单…")


def menu_restore_original():
    device = get_first_device()
    if not device:
        console.print("\n[red]未连接已信任的 USB iPhone。[/red]")
        input("\n按回车键返回菜单…")
        return

    cards = load_saved_cards()
    available = [(card, latest_backup(device.udid, card)) for card in cards]
    available = [(card, record) for card, record in available if record]
    if not available:
        console.print("\n[yellow]这台 iPhone 没有可用的原始卡面备份。[/yellow]")
        input("\n按回车键返回菜单…")
        return

    console.print("\n[bold cyan]选择要恢复的卡片备份：[/bold cyan]")
    for index, (card, record) in enumerate(available, 1):
        console.print(f"  [{index}] {card}  [dim]({record.label})[/dim]")
    value = input(f"\n请输入卡片编号（1-{len(available)}）[1]：").strip() or "1"
    try:
        card_hash, record = available[int(value) - 1]
    except (ValueError, IndexError):
        console.print("[red]选择无效。[/red]")
        return

    confirm = input("恢复并校验已保存的原始卡面？(y/N)：").strip().lower()
    if confirm not in ("y", "yes"):
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("正在恢复原始卡面…", total=1)

        def update_progress(step: int, total: int, message: str):
            progress.update(task, completed=step, total=max(1, total), description=message)

        try:
            asyncio.run(
                restore_original_card_async(
                    device.udid,
                    card_hash,
                    backup=record,
                    verify=True,
                    progress_callback=update_progress,
                )
            )
            console.print("[bold green]原始卡面已恢复并通过校验。[/bold green]")
        except Exception as exc:
            console.print(f"[bold red]恢复失败：[/bold red] {exc}")
    input("\n按回车键返回菜单…")


def main():
    while True:
        show_banner()
        console.print("\n[bold white]操作：[/bold white]")
        console.print("  [bold cyan]1[/bold cyan] - 📡 扫描卡片（在 iPhone 上打开 Wallet 并点选卡片）")
        console.print("  [bold cyan]2[/bold cyan] - 📋 查看或管理已保存卡片")
        console.print("  [bold cyan]3[/bold cyan] - 🎨 应用自定义卡面")
        console.print("  [bold cyan]4[/bold cyan] - ♻️ 恢复原始卡面")
        console.print("  [bold cyan]5[/bold cyan] - 🔄 刷新连接")
        console.print("  [bold cyan]0[/bold cyan] - ❌ 退出")

        choice = input("\n请选择 [1]：").strip()
        if choice in ("", "1"):
            menu_scan_cards()
        elif choice == "2":
            menu_view_cards()
        elif choice == "3":
            menu_flash_skin()
        elif choice == "4":
            menu_restore_original()
        elif choice == "5":
            continue
        elif choice == "0":
            console.print("[dim]再见！[/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()
