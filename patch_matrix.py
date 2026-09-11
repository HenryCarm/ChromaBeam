import re

with open("core/color_matrix.py", "r") as f:
    content = f.read()

# 1. Update module_scale to be larger
content = re.sub(r'self\.module_scale = max\(1, grid_size // 56\)', r'self.module_scale = max(1, grid_size // 24)', content)

# 2. Add white separators around the anchors
# In __init__:
init_replacement = """        # 3 Corners reserved for 1:1:3:1:1 standard QR finder patterns + 1 module white separator
        s_with_sep = s + self.module_scale
        self.data_mask[0:s_with_sep, 0:s_with_sep] = False
        self.data_mask[0:s_with_sep, N-s_with_sep:N] = False
        self.data_mask[N-s_with_sep:N, 0:s_with_sep] = False"""
content = re.sub(r'        # 3 Corners reserved.*?self\.data_mask\[N-s:N, 0:s\] = False', init_replacement, content, flags=re.DOTALL)

# In render_anchors:
render_replacement = """        # Top-Left (with white separator)
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
content = re.sub(r'        # Top-Left.*?grid\[N-s\+2\*m:N-2\*m, 2\*m:s-2\*m\] = black', render_replacement, content, flags=re.DOTALL)

with open("core/color_matrix.py", "w") as f:
    f.write(content)
