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
from .device import get_first_device
from .scanner import load_saved_cards, save_cards, start_card_scan_session
from .image_util import prepare_card_skin
from .core_flasher import flash_card_skin

console = Console()


def show_banner():
    console.clear()
    dll_dir = find_apple_dll_dir()
    dll_status = "[green]Detected (iTunes Support)[/green]" if dll_dir else "[red]Not found (Install iTunes!)[/red]"

    device = get_first_device()
    if device:
        dev_text = f"[green]Connected:[/green] {device.name} ([cyan]{device.product_type}[/cyan], iOS {device.ios_version})"
    else:
        dev_text = "[yellow]Not connected (Plug in iPhone via USB & Unlock)[/yellow]"

    banner_text = (
        "[bold cyan]🎴 AirCard for Windows[/bold cyan]\n"
        "[dim]Apple Wallet & Apple Pay Card Skinner (Native Windows Airlift Engine)[/dim]\n\n"
        f"📱 [bold]iPhone:[/bold] {dev_text}\n"
        f"📦 [bold]Apple Mobile Device Support:[/bold] {dll_status}"
    )
    console.print(Panel(banner_text, border_style="cyan", expand=False))


def menu_scan_cards():
    console.print("\n[bold yellow]📡 Real-time Apple Wallet Card Scanner[/bold yellow]")
    console.print("=" * 60)
    console.print("To capture your card hash:")
    console.print("  👉 [bold white]1.[/bold white] Double-click Side / Home button on your iPhone to open Apple Pay.")
    console.print("  👉 [bold white]2.[/bold white] Authenticate with Face ID / Touch ID.")
    console.print("  👉 [bold white]3.[/bold white] Tap your card on screen to trigger instant detection!")
    console.print("\n[dim]Press ENTER or Ctrl+C when finished scanning.[/dim]")
    console.print("=" * 60 + "\n")

    stop_event = asyncio.Event()

    def on_card(card_hash: str, total_count: int):
        console.print(f"  ✨ [bold green]Detected Card [{total_count}]:[/bold green] [cyan]{card_hash}[/cyan]")
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except Exception:
            pass

    async def run_scan():
        task = asyncio.create_task(start_card_scan_session(on_card_found=on_card, stop_event=stop_event))
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, input, "Scanning... Press ENTER to stop: ")
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
        console.print(f"\n[bold red]Scanner error:[/bold red] [yellow]{e}[/yellow]")
        console.print("[dim]Make sure your iPhone is connected, unlocked, and 'Trust this Computer' is accepted.[/dim]")

    cards = load_saved_cards()
    console.print(f"\n[green]✅ Scanning complete. Total saved cards: {len(cards)}[/green]")
    input("\nPress ENTER to return to menu...")


def menu_view_cards():
    cards = load_saved_cards()
    console.print(f"\n[bold]Saved Apple Wallet Cards ({len(cards)}):[/bold]")
    if not cards:
        console.print("[dim]No cards saved yet. Use option [1] to scan cards from your iPhone.[/dim]")
    else:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Card Hash (Pass Identifier)", style="cyan")

        for idx, h in enumerate(cards, 1):
            table.add_row(str(idx), h)
        console.print(table)

    console.print("\n[1] Add card hash manually")
    console.print("[2] Delete a card")
    console.print("[3] Clear all cards")
    console.print("[Enter] Back to main menu")

    choice = input("\nChoice: ").strip()
    if choice == "1":
        manual = input("Enter card hash: ").strip()
        if len(manual) >= 20:
            cards.append(manual)
            save_cards(cards)
            console.print("[green]Card saved![/green]")
    elif choice == "2":
        num = input("Enter card # to delete: ").strip()
        try:
            idx = int(num) - 1
            if 0 <= idx < len(cards):
                removed = cards.pop(idx)
                save_cards(cards)
                console.print(f"[yellow]Removed {removed}[/yellow]")
        except Exception:
            pass
    elif choice == "3":
        confirm = input("Are you sure you want to clear all cards? (y/n): ").strip().lower()
        if confirm == "y":
            save_cards([])
            console.print("[yellow]Cleared all saved cards.[/yellow]")


def menu_flash_skin():
    cards = load_saved_cards()
    if not cards:
        console.print("\n[red]No cards found! Please scan your cards first using option [1].[/red]")
        input("\nPress ENTER to return to menu...")
        return

    console.print("\n[bold cyan]Choose target card:[/bold cyan]")
    for idx, h in enumerate(cards, 1):
        console.print(f"  [{idx}] {h}")

    card_choice = input(f"\nEnter card number (1-{len(cards)}) or 'all' [1]: ").strip()
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
                console.print("[red]Invalid choice.[/red]")
                return
        except ValueError:
            console.print("[red]Invalid choice.[/red]")
            return

    console.print("\n[bold cyan]Select card skin image:[/bold cyan]")
    while True:
        img_path = input("Drag & drop image file here (PNG/JPG/WebP) or enter path: ").strip().strip("'\"")
        if not img_path:
            return
        try:
            console.print("[dim]Processing image (converting & scaling to 1536x969 PNG)...[/dim]")
            skin_bytes = prepare_card_skin(img_path)
            console.print(f"[green]✓ Image ready ({len(skin_bytes):,} bytes)[/green]\n")
            break
        except Exception as e:
            console.print(f"[red]Error with image: {e}. Try another file.[/red]")

    for card_idx, target_card in enumerate(selected_cards, 1):
        console.print(f"[bold]Flashing card [{card_idx}/{len(selected_cards)}]:[/bold] [cyan]{target_card}[/cyan]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Connecting...", total=6)

            def update_progress(step: int, total: int, msg: str):
                progress.update(task, completed=step, total=total, description=msg)

            success = flash_card_skin(None, target_card, skin_bytes, progress_callback=update_progress)

        if success:
            console.print(f"[bold green]🎉 SUCCESS: Card {target_card[:10]}... updated![/bold green]")
        else:
            console.print(f"[bold red]❌ FAILED: Could not update card {target_card}.[/bold red]")

    console.print("\n" + "=" * 60)
    console.print("[bold green]All done![/bold green]")
    console.print("👉 Force-close the [bold]Wallet[/bold] app on your iPhone and reopen Apple Pay to view your new card!")
    console.print("=" * 60)
    input("\nPress ENTER to return to menu...")


def main():
    while True:
        show_banner()
        console.print("\n[bold white]Actions:[/bold white]")
        console.print("  [bold cyan]1[/bold cyan] - 📡 Scan Cards (Open Wallet on iPhone & Tap Card)")
        console.print("  [bold cyan]2[/bold cyan] - 📋 View / Manage Saved Cards")
        console.print("  [bold cyan]3[/bold cyan] - 🎨 Flash Custom Skin to Card")
        console.print("  [bold cyan]4[/bold cyan] - 🔄 Refresh Connection")
        console.print("  [bold cyan]0[/bold cyan] - ❌ Exit")

        choice = input("\nSelect option [1]: ").strip()
        if choice in ("", "1"):
            menu_scan_cards()
        elif choice == "2":
            menu_view_cards()
        elif choice == "3":
            menu_flash_skin()
        elif choice == "4":
            continue
        elif choice == "0":
            console.print("[dim]Goodbye![/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()
