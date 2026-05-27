"""
scibot/visualization
V13 可视化渲染模块
- render_d3: D3.js 交互式 HTML
- render_png: 高清 PNG (matplotlib)
"""

from .render_d3 import render_interactive_html
from .render_png import render_static_png

__all__ = ["render_interactive_html", "render_static_png"]
