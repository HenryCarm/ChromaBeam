import re

with open("main.py", "r") as f:
    content = f.read()

# Replace self.stop() in stop_sender and stop_receiver with a proper reset to main screen
reset_ui = """        self.layout.clear_widgets()
        self.layout.add_widget(self.title_lbl)
        self.layout.add_widget(self.send_btn)
        self.layout.add_widget(self.recv_btn)
        self.layout.add_widget(self.adv_btn)
        self.layout.add_widget(self.adv_layout)"""

content = content.replace("        self.stop()", reset_ui)

with open("main.py", "w") as f:
    f.write(content)
