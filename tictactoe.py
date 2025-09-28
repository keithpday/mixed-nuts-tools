import tkinter as tk
from tkinter import messagebox

PLAYER_X = "X"
PLAYER_O = "O"

class TicTacToe:
    def __init__(self):
        self.window = tk.Tk()
        self.window.title("Tic Tac Toe")

        self.current_player = PLAYER_X
        self.board = [[None, None, None],
                      [None, None, None],
                      [None, None, None]]

        self.buttons = []
        for i in range(3):
            row = []
            for j in range(3):
                button = tk.Button(self.window, text=" ", font=("Helvetica", 20), width=6, height=3,
                                   command=lambda row=i, col=j: self.make_move(row, col))
                button.grid(row=i, column=j)
                row.append(button)
            self.buttons.append(row)

    def make_move(self, row, col):
        if self.board[row][col] is None:
            self.board[row][col] = self.current_player
            self.buttons[row][col].config(text=self.current_player)
            self.check_winner()
            self.switch_players()

    def switch_players(self):
        self.current_player = PLAYER_O if self.current_player == PLAYER_X else PLAYER_X

    def check_winner(self):
        for i in range(3):
            if self.board[i][0] == self.board[i][1] == self.board[i][2] == self.current_player:
                self.show_winner_message()
                self.restart_game()
                return

            if self.board[0][i] == self.board[1][i] == self.board[2][i] == self.current_player:
                self.show_winner_message()
                self.restart_game()
                return

        if self.board[0][0] == self.board[1][1] == self.board[2][2] == self.current_player:
            self.show_winner_message()
            self.restart_game()
            return

        if self.board[0][2] == self.board[1][1] == self.board[2][0] == self.current_player:
            self.show_winner_message()
            self.restart_game()
            return

    def show_winner_message(self):
        messagebox.showinfo("Game Over", f"Player {self.current_player} wins!")

    def restart_game(self):
        self.current_player = PLAYER_X
        self.board = [[None, None, None],
                      [None, None, None],
                      [None, None, None]]
        for i in range(3):
            for j in range(3):
                self.buttons[i][j].config(text=" ")

    def run(self):
        self.window.mainloop()

if __name__ == "__main__":
    game = TicTacToe()
    game.run()
