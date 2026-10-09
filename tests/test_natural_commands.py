import pytest

from jarvis.core import parse_command


@pytest.mark.parametrize("text, expected", [
    ("Hey Jarvis, could you please open GoogleChrome?", ("open_app", "google chrome")),
    ("can you open Chrome.", ("open_app", "chrome")),
    ("Could you please do open chrome!", ("open_app", "chrome")),
    ("I would like you to open Calculator", ("open_app", "Calculator")),
    ("I'd like you to launch Google Chrome", ("open_app", "google chrome")),
    ("do me a favour and open Notepad", ("open_app", "Notepad")),
    ("Please open spot ify.", ("spotify", "play")),
    ("can you start spot if y", ("spotify", "play")),
    ("open Spot X", ("spotify", "play")),
    ("play music on Spotify", ("spotify", "play")),
    ("please play my music on spot ify!", ("spotify", "play")),
    ("play some music", ("spotify", "play")),
    ("put on the music on Spotify.", ("spotify", "play")),
    ("start playing music on Spotify", ("spotify", "play")),
    ("playmusic onSpotify", ("spotify", "play")),
    ("turn on Spotify", ("spotify", "play")),
    ("Could you pause the spot ify?", ("spotify", "pause")),
    ("please resume Spot Ify.", ("spotify", "play")),
    ("can you skip track?", ("spotify", "next")),
    ("please turn the volume up", ("media_key", "volume up")),
    ("could you lower volume?", ("media_key", "volume down")),
    ("can you go to sleep?", ("sleep", "")),
    ("would you show me my tasks?", ("list_tasks", "")),
    ("Could you tell me the time?", ("clock", "tell me the time")),
    ("please search that!", ("chrome_submit", "")),
    ("press enter in Chrome", ("chrome_submit", "")),
])
def test_natural_command_wrappers_and_app_aliases(text, expected):
    assert parse_command(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("set the volume to fifty percent", ("volume", "50")),
    ("please change volume to seventy five percent.", ("volume", "75")),
    ("volume ninety-nine per cent?", ("volume", "99")),
    ("volume 50%", ("volume", "50")),
    ("set volume one hundred", ("volume", "100")),
    ("volume a hundred percent", ("volume", "100")),
    ("volume zero percent", ("volume", "0")),
    ("complete task two", ("complete_task", "2")),
    ("finish task number twenty one.", ("complete_task", "21")),
    ("please mark task twelve as done", ("complete_task", "12")),
    ("mark the task number forty two complete", ("complete_task", "42")),
    ("remove task nine", ("remove_task", "9")),
    ("could you delete the task number one hundred and two?", ("remove_task", "102")),
    ("complete task 1000", ("complete_task", "1000")),
    ("complete the second task", ("complete_task", "2")),
    ("mark the third task as done", ("complete_task", "3")),
    ("remove the twenty-first task", ("remove_task", "21")),
    ("delete task one hundred and second", ("remove_task", "102")),
])
def test_spoken_numbers_are_structural_arguments(text, expected):
    assert parse_command(text) == expected


@pytest.mark.parametrize("text, action, argument", [
    ('Could you please play "Please Please Please"?', "spotify_play_song", "Please Please Please"),
    ("play 'What's Up?'!", "spotify_play_song", "What's Up?"),
    ('play “Music on Spotify”.', "spotify_play_song", "Music on Spotify"),
    ('play "Spotify"', "spotify_play_song", "Spotify"),
    ('play "music"', "spotify_play_song", "music"),
    ('play the song "Hello by Adele" on Spotify.', "spotify_play_song", "Hello by Adele"),
    ("play Song 2", "spotify_play_song", "Song 2"),
    ("play The Song Remains the Same", "spotify_play_song", "The Song Remains the Same"),
    ("play a song called Twenty One", "spotify_play_song", "Twenty One"),
    ("play Can You Feel the Love Tonight", "spotify_play_song", "Can You Feel the Love Tonight"),
    ("play What's Up?", "spotify_play_song", "What's Up?"),
    ("play Do You Really Want to Hurt Me", "spotify_play_song", "Do You Really Want to Hurt Me"),
    ("play One Hundred Ways", "spotify_play_song", "One Hundred Ways"),
    ("start playing Hello by Adele onSpotify", "spotify_play_song", "Hello by Adele"),
    ("search Spotify for Please Please Please", "spotify_search", "Please Please Please"),
    ("search on spot ify for \"Don't Stop Me Now\".", "spotify_search", "Don't Stop Me Now"),
    ('search for "Please Please Please" on Spotify.', "spotify_search", "Please Please Please"),
    ('can you add task "Call Jarvison, please!"?', "add_task", "Call Jarvison, please!"),
    ("create a task called Buy Two Cakes", "add_task", "Buy Two Cakes"),
    ("add task: Please email Jarvison", "add_task", "Please email Jarvison"),
    ("add task To Be or Not To Be", "add_task", "To Be or Not To Be"),
    ("add task called Sarah yesterday", "add_task", "called Sarah yesterday"),
    ("remind me to Set Volume to Fifty", "add_task", "Set Volume to Fifty"),
    ("add Call Jarvison to my task list.", "add_task", "Call Jarvison"),
    ("new task: Watch Iron Man", "add_task", "Watch Iron Man"),
    ('search GoogleChrome for "What is Spotify?"!', "chrome_search", "What is Spotify?"),
    ('search for "Could You Be Loved" in Chrome.', "chrome_search", "Could You Be Loved"),
    ("type London Weather in the Chrome search bar", "chrome_type", "London Weather"),
    ('write "Hey Jarvis, please open Spotify!" into Chrome address bar.', "chrome_type", "Hey Jarvis, please open Spotify!"),
    ("type in Chrome One Hundred & Twenty", "chrome_type", "One Hundred & Twenty"),
    ('type in the search bar "fish & chips {ENTER}".', "chrome_type", "fish & chips {ENTER}"),
    ("look up How Can You Open Spotify?", "search_web", "How Can You Open Spotify?"),
    ("google Please Please Please", "search_web", "Please Please Please"),
    ("can you say hello to Sarah", "greet", "Sarah"),
    ("please say hi to Xavier", "greet", "Xavier"),
    ('greet "Dr. O’Connor"!', "greet", "Dr. O’Connor"),
    ("Could you greet Jarvison", "greet", "Jarvison"),
    ("can you say Hello, everyone!", "say", "Hello, everyone!"),
    ('repeat "Please open Spotify!".', "say", "Please open Spotify!"),
    ("say Add task buy milk", "say", "Add task buy milk"),
    ("do say hello to Sarah", "greet", "Sarah"),
])
def test_command_words_numbers_quotes_and_punctuation_inside_arguments_survive(text, action, argument):
    assert parse_command(text) == (action, argument)


@pytest.mark.parametrize("text, expected", [
    ("Jarvison open Chrome", ("conversation", "Jarvison open Chrome")),
    ("Jarvis's favourite song", ("conversation", "Jarvis's favourite song")),
    ("hey Jarvison play music", ("conversation", "hey Jarvison play music")),
    ("add task Jarvison meeting", ("add_task", "Jarvison meeting")),
    ("play Jarvison", ("spotify_play_song", "Jarvison")),
    ("Hey Jar Vus, play music", ("spotify", "play")),
    ("hey Jar V Is open chrome", ("open_app", "chrome")),
])
def test_wake_prefix_has_boundaries_and_does_not_change_arguments(text, expected):
    assert parse_command(text) == expected


@pytest.mark.parametrize("text", [
    "volume one two", "set volume three point five", "remove task for",
    "complete task to", "delete task twenty sixteen", "volume one hundred and",
    "volume zero hundred", "add taskmaster", "Can you tell me a story?",
    "can you run an arbitrary shell command", "please do everything in the movies",
    "do my homework", "restart my computer", "install and execute this script",
    "playground", "volume fifth", "complete the one second task",
    "add task:", "new task:", "add task :", "new task :",
])
def test_ambiguous_numbers_unknown_commands_and_conversation_are_not_guessed(text):
    assert parse_command(text) == ("conversation", text)
