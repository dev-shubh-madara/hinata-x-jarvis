"""
One "Hinata session": from the moment you press the hotkey until she goes
back to the small orb.

  * Chatting / questions / anything that needs no work on the PC
        -> the hologram STAYS OPEN and she keeps listening for your next
           sentence (no hotkey needed in between).
  * Real work (open, make, play, pair phone, type, volume...)
        -> she does it, answers in a few words, and the hologram closes so
           you can see the result. Press the hotkey to bring her back.
  * Waiting for your "confirm" / "cancel"
        -> stays open and listens.
  * "Okay Hinata, let's continue with our work" / "that's all" / "bye"
        -> she says goodbye and closes.
  * Silence for CONVO_IDLE_SECONDS -> she closes by herself.

Kept free of any Windows / UI imports so it can be tested with fake input.
"""

import time


def run_session(*, overlay, typed, listen, ask_command, run_command, speak,
                chime=lambda: None, drain=lambda: None, is_end=lambda text: False,
                conversation_mode=True, first_timeout=5, follow_timeout=8,
                idle_seconds=30, clock=time.time) -> str:
    """Returns why it ended: 'action', 'ended', 'idle' or 'nothing heard'."""
    first = True
    last_heard = clock()
    overlay.set_info("MODE", "COMMAND")
    if not typed:
        overlay.expand()
        overlay.set_caption(you="", reply="")

    while True:
        if typed:
            text = ask_command()
        else:
            overlay.set_state("listening")
            if first:
                chime()
            text = listen(first_timeout if first else follow_timeout)

        if getattr(overlay, "consume_sleep", lambda: False)():
            return "sleep"                          # right-clicked the hologram: back to the orb
        if not text:
            if typed:
                return "idle"                       # command bar closed with Esc
            if first:
                overlay.set_state("speaking")
                speak("Sorry, I didn't catch that.")
                return "nothing heard"
            if clock() - last_heard > idle_seconds:
                return "idle"
            continue                                 # quiet moment - keep listening

        first = False
        last_heard = clock()
        if typed:
            overlay.expand()

        if is_end(text):
            overlay.set_caption(you=text, reply="")
            overlay.set_state("speaking")
            speak("Okay, I'm here whenever you need me.")
            return "ended"

        outcome = run_command(text)                  # 'chat' | 'confirm' | 'action'
        drain()                                      # drop hotkey taps made while she talked
        if getattr(overlay, "consume_sleep", lambda: False)():
            return "sleep"
        if outcome == "action" or not conversation_mode:
            return "action"

        overlay.set_info("MODE", "CONVERSATION")
        last_heard = clock()
