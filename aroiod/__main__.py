"""python -m aroiod [--sim] [--data DIR] [--port N] [--static DIR]

On the device systemd starts it without --sim (real world: phase 1). For
development ./dev.sh starts it with --sim next to the Vite dev server.
"""

import argparse
import logging
from pathlib import Path

from aiohttp import web

from .engine import Device
from .hub import Hub
from .web import build_app
from .wizard import RoomWizard


def create(data_dir, sim=True, model="AroioLT", board="pi4", fast=False, mic_mode="none"):
    if sim:
        from .sim import SimWorld
        world = SimWorld(model=model, board=board, fast=fast, mic_mode=mic_mode)
    else:
        from .real import RealWorld
        world = RealWorld()
    hub = Hub()
    device = Device(data_dir, world, hub)
    world.attach(device)
    device.wizard = RoomWizard(device)
    return device


def main():
    ap = argparse.ArgumentParser(prog="aroiod")
    ap.add_argument("--sim", action="store_true", help="simulierte Hardware")
    ap.add_argument("--data", default="/data/aroio")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--static", default=str(Path(__file__).resolve().parent.parent / "web" / "dist"))
    ap.add_argument("--model", default="AroioLT")
    ap.add_argument("--board", default="pi4")
    ap.add_argument("--mic", default="sim", choices=["sim", "none", "host"],
                    help="Simulator: Messmikrofon (sim = virtueller Raum, host = echtes Mikrofon im Simulator-Browser)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    device = create(args.data, sim=args.sim, model=args.model, board=args.board, mic_mode=args.mic)
    app = build_app(device, args.static)

    async def on_start(_app):
        if hasattr(device.world, "start"):
            device.world.start()
        device.start()
        device.wizard.publish()
        device.world.publish_sim()

    app.on_startup.append(on_start)
    web.run_app(app, host=args.host, port=args.port, access_log=logging.getLogger("aiohttp.access") if args.verbose else None,
                print=lambda *_: logging.info(
        "aroiod läuft auf http://localhost:%s  (Simulator: /sim)", args.port))


if __name__ == "__main__":
    main()
