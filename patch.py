import re

with open("core/color_matrix.py", "r") as f:
    content = f.read()

# 1. Update module_scale
content = content.replace("max(1, grid_size // 56)", "max(1, grid_size // 24)")

# 2. Update __init__ mask
old_init = """        # 3 Corners reserved for 1:1:3:1:1 standard QR finder patterns (TL, TR, BL)
        self.data_mask[0:s, 0:s] = False
        self.data_mask[0:s, N-s:N] = False
        self.data_mask[N-s:N, 0:s] = False"""
new_init = """        # 3 Corners reserved for 1:1:3:1:1 standard QR finder patterns + 1 module white separator
        s_with_sep = s + self.module_scale
        self.data_mask[0:s_with_sep, 0:s_with_sep] = False
        self.data_mask[0:s_with_sep, N-s_with_sep:N] = False
        self.data_mask[N-s_with_sep:N, 0:s_with_sep] = False"""
content = content.replace(old_init, new_init)

# 3. Update render_anchors
old_render = """        # Top-Left
        grid[0:s, 0:s] = black
        grid[m:s-m, m:s-m] = white
        grid[2*m:s-2*m, 2*m:s-2*m] = black

        # Top-Right
        grid[0:s, N-s:N] = black
        grid[m:s-m, N-s+m:N-m] = white
        grid[2*m:s-2*m, N-s+2*m:N-2*m] = black

        # Bottom-Left
        grid[N-s:N, 0:s] = black
        grid[N-s+m:N-m, m:s-m] = white
        grid[N-s+2*m:N-2*m, 2*m:s-2*m] = black"""

new_render = """        # Top-Left (with white separator)
        grid[0:s+m, 0:s+m] = white
        grid[0:s, 0:s] = black
        grid[m:s-m, m:s-m] = white
        grid[2*m:s-2*m, 2*m:s-2*m] = black

        # Top-Right
        grid[0:s+m, N-s-m:N] = white
        grid[0:s, N-s:N] = black
        grid[m:s-m, N-s+m:N-m] = white
        grid[2*m:s-2*m, N-s+2*m:N-2*m] = black

        # Bottom-Left
        grid[N-s-m:N, 0:s+m] = white
        grid[N-s:N, 0:s] = black
        grid[N-s+m:N-m, m:s-m] = white
        grid[N-s+2*m:N-2*m, 2*m:s-2*m] = black"""
content = content.replace(old_render, new_render)

with open("core/color_matrix.py", "w") as f:
    f.write(content)
