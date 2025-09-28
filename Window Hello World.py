import tkinter as tk

def button_pressed(label_text):
    print(label_text)

def create_window():
    window = tk.Tk()
    window.title("Button Example")

    yes_button = tk.Button(window, text="Yes", command=lambda: button_pressed("Yes"))
    yes_button.pack()

    no_button = tk.Button(window, text="No", command=lambda: button_pressed("Nope"))
    no_button.pack()

    window.mainloop()

create_window()
