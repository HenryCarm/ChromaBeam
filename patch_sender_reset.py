import re

with open("desktop_app.py", "r") as f:
    content = f.read()

# Remove the self.total_droplets_sent = 0 from _toggle_stream
content = re.sub(r'self\.start_stream_time = time\.time\(\)\n\s*self\.total_droplets_sent = 0', 'self.start_stream_time = time.time()', content)

with open("desktop_app.py", "w") as f:
    f.write(content)
