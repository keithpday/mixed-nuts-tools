import PySimpleGUI as psg

layout = [
    [psg.Text("Enter your name:", key="lbl")],
    [psg.Input(key="name")],
    [psg.Button("Greet"), psg.Button("Exit")],
    [psg.Text("", key="output")]
]

window = psg.Window("My First GUI", layout)

while True:
    event, values = window.read()
    if event in (psg.WIN_CLOSED, "Exit"):
        break
    if event == "Greet":
        window["output"].update(f"Hello, {values['name']}!")

window.close()
