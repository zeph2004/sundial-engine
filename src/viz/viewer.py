import sys
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def launch_viewer(port: int = 8050) -> None:
    """
    Launches a lightweight local HTTP server rooted at the repository directory
    and opens the interactive Timetable Visualizer & A4 Landscape PDF Renderer
    (`src/viz/index.html`) in the default browser.
    """
    root = Path(__file__).resolve().parents[2]
    data_bundle = root / "data" / "processed" / "timetable_view_data.json"
    if not data_bundle.exists():
        print("[Viewer] Timetable bundle not found. Running CSP solver first...")
        import subprocess
        subprocess.run([sys.executable, str(root / "src" / "csp" / "solver.py")], check=True)

    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/src/viz/index.html"

    print(f"========================================================================")
    print(f"  Sundial Engine — Interactive Timetable Visualizer & PDF Renderer")
    print(f"========================================================================")
    print(f"  URL        : {url}")
    print(f"  Local File : {(root / 'src' / 'viz' / 'index.html').as_uri()}")
    print(f"  Press Ctrl+C to stop the server.")
    print(f"========================================================================")

    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Viewer] Shutting down server.")
        server.server_close()


if __name__ == "__main__":
    launch_viewer()
