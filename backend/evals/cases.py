"""Real requests and what Jarvis must do for each.

  say       what the user says
  tools     tool calls that must happen, in this order (others may happen too)
  args      {tool: {arg: regex}} checked against that tool's first call
  forbid    tools that must NOT be called
  no_tools  True: answer in words, call nothing
  reply     regex the final reply must match; reply_not: must NOT match
  phone     True: the message comes from Telegram
"""

ME = "asfansalah46@gmail.com"
WEATHER_CHAT = [
    {"role": "user", "content": "what's the weather today"},
    {"role": "assistant", "content": "It's 16°C and cloudy in London, with light rain likely from 6pm.",
     "meta": {"agent": "research", "tools": [{"name": "weather", "arguments": {}, "result": "…"}]}},
]

CASES = [
    # --- instant commands / apps / browser -----------------------------------
    {"say": "open youtube", "tools": ["browser_open"], "args": {"browser_open": {"url": "youtube"}}},
    {"say": "Jarvis close the github tab", "tools": ["browser_close_tab"],
     "args": {"browser_close_tab": {"tab": "github"}}},
    {"say": "open safari", "tools": ["open_app"], "args": {"open_app": {"name": "safari"}}},
    {"say": "pause", "tools": ["youtube_control"]},
    {"say": "play drake on youtube", "tools": ["youtube_play"], "args": {"youtube_play": {"query": "drake"}}},
    {"say": "press the subscribe button", "tools": ["browser_click"],
     "args": {"browser_click": {"target": "subscribe"}}},
    {"say": "click on sign in", "tools": [["browser_click", "click_on_screen"]],
     "args": {"browser_click": {"target": "sign in"}, "click_on_screen": {"target": "sign in"}}},
    {"say": "what tabs do I have open", "tools": ["browser_tabs"]},
    {"say": "go to bbc.co.uk", "tools": [["browser_open", "open_url"]],
     "args": {"browser_open": {"url": "bbc"}, "open_url": {"url": "bbc"}}},
    {"say": "quit spotify", "tools": ["quit_app"], "args": {"quit_app": {"name": "spotify"}}},

    # --- files -----------------------------------------------------------------
    {"say": "list all the files on my desktop", "tools": ["list_directory"],
     "args": {"list_directory": {"path": "desktop"}}},
    {"say": "open my CV", "tools": ["open_file"], "args": {"open_file": {"path": "cv"}}},
    {"say": "open the lease pdf", "tools": ["open_file"], "args": {"open_file": {"path": "lease"}}},
    {"say": "find my tax return", "tools": [["search_files", "search_documents"]],
     "args": {"search_files": {"query": "tax"}, "search_documents": {"query": "tax"}}},
    {"say": "what's my latest screenshot on the desktop", "tools": ["list_directory"],
     "args": {"list_directory": {"sort": "recent"}}},
    {"say": "make a folder on my desktop called Invoices", "tools": ["create_folder"],
     "args": {"create_folder": {"path": "(?i)desktop/invoices"}}},
    {"say": "move notes.txt from my desktop into the Spain folder", "tools": ["move_file"],
     "args": {"move_file": {"source": "notes.txt", "destination": "spain"}}},
    {"say": "delete notes.txt on my desktop", "tools": ["trash_file"],
     "args": {"trash_file": {"path": "notes.txt"}}},

    # --- documents + email ---------------------------------------------------------
    {"say": f"write a word document with a shopping list of milk, eggs and bread and email it to {ME}",
     "tools": ["create_word_document", "send_email"],
     "args": {"send_email": {"to": ME, "attachments": r"\.docx"}}},
    {"say": f"email my CV to {ME}", "tools": ["send_email"],
     "args": {"send_email": {"to": ME, "attachments": "cv"}}, "forbid": ["draft_email"]},
    {"say": f"draft an email to {ME} saying I'll be late tomorrow", "tools": ["draft_email"],
     "args": {"draft_email": {"to": ME, "body": "late"}}, "forbid": ["send_email"]},
    {"say": "do I have any new emails", "tools": ["read_emails"],
     "args": {"read_emails": {"unread_only": "true"}}},
    {"say": "summarize my emails", "tools": ["read_emails"]},
    {"say": "find emails from Amazon", "tools": [["search_emails", "read_emails"]],
     "args": {"search_emails": {"query": "amazon"}}},
    {"say": "write a report about electric cars as a word document", "tools": [["research_report", "create_word_document"]],
     "args": {"create_word_document": {"content": "(?s).{300,}"}}},
    {"say": "text John that I'm running late", "tools": ["draft_imessage"],
     "people": [{"name": "John Smith", "phone": "+44 7700 900123"}],
     "args": {"draft_imessage": {"recipient": "john", "body": "late"}}},

    # --- calendar / reminders / notes -------------------------------------------------
    {"say": "what's on my calendar today", "tools": [["calendar_today", "calendar_events"]]},
    {"say": "what do I have this week", "tools": ["calendar_events"]},
    {"say": "remind me to call mum at 6pm", "tools": ["create_reminder"],
     "args": {"create_reminder": {"title": "mum", "due": "18|6"}}},
    {"say": "create a note called Ideas with: build a robot arm", "tools": ["create_note"],
     "args": {"create_note": {"title": "ideas", "body": "robot"}}},
    {"say": "add a meeting with Sam tomorrow at 3pm to my calendar", "tools": ["calendar_create_event"],
     "args": {"calendar_create_event": {"title": "sam", "start": "15:00|3"}}},

    # --- vision / screen -------------------------------------------------------------------
    {"say": "what's on my screen", "tools": [["screen_look", "screen_read"]]},
    {"say": "read the text on my screen", "tools": ["screen_read"]},
    {"say": "open the camera and tell me what you see", "tools": ["camera_look"]},
    {"say": "can you open camera and tell me what can you see?", "tools": ["camera_look"]},
    {"say": "take a picture", "tools": ["take_photo"]},
    {"say": "take a photo of me and send it to my phone", "tools": ["take_photo"],
     "args": {"take_photo": {"send_to_phone": "true"}}},
    {"say": "snap a quick photo with the webcam then send it over to me on telegram",
     "tools": ["take_photo"], "reply_not": r"(?i)can'?t|cannot|unable"},
    {"say": "send me the picture you just took", "tools": ["send_to_phone"],
     "args": {"send_to_phone": {"what": "photo"}},
     "history": [{"role": "user", "content": "take a picture"},
                 {"role": "assistant", "content": "Took a photo and saved it at /Users/salah/Pictures/Jarvis/photo-2026-10-14-22-30-15.jpg.",
                  "meta": {"agent": "quick", "tools": [{"name": "take_photo", "arguments": {},
                           "result": "Took a photo and saved it at /Users/salah/Pictures/Jarvis/photo-2026-10-14-22-30-15.jpg."}]}}]},

    # --- calls -------------------------------------------------------------------------------
    {"say": "facetime mum", "tools": ["facetime_call"], "args": {"facetime_call": {"contact": "mum"}},
     "people": [{"name": "Mum", "relation": "mum", "phone": "07700 900333"}]},
    {"say": "could you give my mum a quick video call", "tools": ["facetime_call"],
     "args": {"facetime_call": {"contact": "mum", "kind": "video"}},
     "people": [{"name": "Mum", "relation": "mum", "phone": "07700 900333"}]},
    {"say": "call my landlord on facetime audio please", "tools": ["facetime_call"],
     "args": {"facetime_call": {"contact": "landlord", "kind": "audio"}},
     "people": [{"name": "Tom", "relation": "landlord", "phone": "07700 900444"}]},

    # --- agent teams ---------------------------------------------------------------------------
    {"say": "ask my startup team to build a landing page and a launch plan for a dog-walking app",
     "tools": ["run_agent_team"], "args": {"run_agent_team": {"task": "dog"}}},
    {"say": "tell me when the download finishes on my screen", "tools": ["watch_screen"],
     "args": {"watch_screen": {"condition": "download"}}},

    # --- research ----------------------------------------------------------------------------
    {"say": "what's the weather in London tomorrow", "tools": ["weather"],
     "args": {"weather": {"place": "london"}}},
    {"say": "what's the latest AI news", "tools": ["research"], "reply": "https?://"},
    {"say": "who won the champions league last season", "tools": ["research"]},

    # --- music ----------------------------------------------------------------------------------
    {"say": "play some Taylor Swift on Apple Music", "tools": ["music_play"],
     "args": {"music_play": {"query": "taylor"}}},

    # --- memory / misc --------------------------------------------------------------------------
    {"say": "remember that my landlord's email is landlord@example.com",
     "tools": [["remember_person", "remember"]],
     "args": {"remember_person": {"email": "landlord@example.com"},
              "remember": {"fact": "landlord@example.com"}}},
    {"say": "email my landlord that the boiler is broken", "people": [
        {"name": "Tom Reed", "relation": "landlord", "email": "tom@example.com"}],
     "tools": ["send_email"], "args": {"send_email": {"to": "tom@example.com|landlord|tom", "body": "boiler"}}},
    {"say": "what's 17% of 2340", "tools": [["calculator"]], "reply": "397\\.8"},
    {"say": "what time is it", "reply": r"\d{1,2}[:.]\d{2}|\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\b"},
    {"say": "give me my daily briefing", "tools": ["daily_briefing"]},

    # --- conversation: no tools -------------------------------------------------------------------
    {"say": "hey jarvis how are you", "no_tools": True},
    {"say": "thanks that's all", "no_tools": True},
    {"say": "explain what a REST API is in two sentences", "reply": "(?i)http|stateless|resource"},
    {"say": "tell me a joke", "no_tools": True},

    # --- me profile & forms -----------------------------------------------------------------------
    {"say": "fill in this form with my details", "tools": ["fill_form"]},
    {"say": "my phone number is 07700 900123", "tools": ["update_my_details"],
     "args": {"update_my_details": {"phone": "07700 ?900123"}}},

    # --- Arabic ---------------------------------------------------------------------------------
    {"say": "ذكرني بالاتصال بأمي الساعة السادسة مساء", "tools": ["create_reminder"],
     "args": {"create_reminder": {"due": "18:00"}}, "reply": "[\u0600-\u06FF]{3,}"},
    {"say": "ما هي عاصمة فرنسا؟", "no_tools": True, "reply": "باريس",
     "reply_not": "[\u4e00-\u9fff]"},
    {"say": "ما هو الطقس في دبي غدا؟", "tools": ["weather"], "reply_not": "[\u4e00-\u9fff]"},

    # --- spoken: short answers you can listen to ------------------------------------------------
    {"say": "what's the latest AI news", "spoken": True, "tools": ["research"], "max_chars": 450},
    {"say": "explain how a heat pump works", "spoken": True, "no_tools": True, "max_chars": 450},
    {"say": "what's on my calendar this week", "spoken": True, "max_chars": 450},

    # --- honesty: a failed send must not be reported as sent --------------------------------------
    {"say": f"email the file nonexistent-xyz.pdf to {ME}", "tools": [],
     "fail": {"send_email": "Attachment not found: nonexistent-xyz.pdf.", "search_files": "No files found."},
     "reply_not": r"(?i)\b(i(?:'ve| have)? sent|has been sent|successfully sent|email sent)\b"},

    # --- routines & triggers -------------------------------------------------------------------
    {"say": "every weekday at 8am send me my daily briefing on telegram", "tools": ["create_routine"],
     "args": {"create_routine": {"at": "8", "action": "brief", "deliver": "telegram"}}},
    {"say": "tell me when an email from my landlord arrives", "tools": ["create_routine"],
     "args": {"create_routine": {"trigger": "email", "email_from": "landlord"}}},
    {"say": "remind me 10 minutes before my meetings", "tools": ["create_routine"],
     "args": {"create_routine": {"trigger": "calendar", "minutes_before": "10"}}},
    {"say": "what routines do I have set up", "tools": ["list_routines"]},

    # --- "this" / "that": what the user is looking at ------------------------------------------
    {"say": f"email this to {ME}", "tools": ["send_email"],
     "this": "App the user is in: Preview\nOpen document: /Users/salah/Documents/lease.pdf  "
             "(read it with read_document; attach this path)",
     "args": {"send_email": {"to": ME, "attachments": "lease.pdf"}}},
    {"say": "summarize this page", "tools": ["browser_read_page"],
     "this": "App the user is in: Google Chrome\nBrowser page: Electric cars explained — "
             "https://example.com/ev  (read it with browser_read_page)"},
    {"say": "what does this mean", "no_tools": True, "reply": "(?i)photosynth|light|plant",
     "this": "App the user is in: Notes\nHighlighted text:\n\"\"\"\nPhotosynthesis converts "
             "light energy into chemical energy in plants.\n\"\"\""},
    {"say": "open this in Finder", "tools": [["open_file"]],
     "this": "App the user is in: Microsoft Word\nOpen document: /Users/salah/Documents/report.docx  "
             "(read it with read_document; attach this path)",
     "args": {"open_file": {"path": "report"}}},

    # --- phone (Telegram) ---------------------------------------------------------------------------
    {"say": "send me my CV", "phone": True, "tools": ["send_file"], "args": {"send_file": {"path": "cv"}}},
    {"say": "send me the latest screenshot from my desktop", "phone": True,
     "tools": ["send_file"], "args": {"send_file": {"path": "screenshot"}}},
    {"say": "Send me the latest 3 files on my desktop", "phone": True,
     "tools": ["list_directory", "send_file"], "reply_not": r"(?i)i'?ll send|let me send"},
    {"say": "Can you write a word document about mcp servers, with deep explanation, then send it to me",
     "phone": True, "tools": [["research_report", "create_word_document"], "send_file"],
     "reply_not": r"(?i)master control|i'?ll send it"},
    {"say": "Send it to me", "phone": True, "tools": [["send_file", "send_to_phone"]],
     "args": {"send_file": {"path": "mcp-servers-overview"}},
     "history": [
         {"role": "user", "content": "Can you write a word document about mcp servers"},
         {"role": "assistant", "content": "I've created the Word document 'MCP Servers Overview'.",
          "meta": {"agent": "general", "tools": [{"name": "create_word_document",
                   "arguments": {"title": "MCP Servers Overview"},
                   "result": "Created Word document 'MCP Servers Overview' (612 words) at "
                             "/Users/salah/Documents/Jarvis/mcp-servers-overview.docx. If the user wants it on their phone, call "
                             "send_file with this path."}]}}]},

    # --- "send it to me" at the Mac = the phone (Telegram) ----------------------------------------
    {"say": "Can you send that to me?", "tools": ["send_to_phone"],
     "args": {"send_to_phone": {"what": "last_answer"}}, "history": WEATHER_CHAT},
    {"say": "could you send the weather you just gave me to my phone", "tools": ["send_to_phone"],
     "reply_not": r"(?i)16\s*°?C.*cloud", "history": WEATHER_CHAT},
    {"say": "send me the whole chat", "tools": ["send_to_phone"],
     "args": {"send_to_phone": {"what": "conversation"}}, "history": WEATHER_CHAT},
    {"say": "put that in a document and send it to me", "tools": ["send_to_phone"],
     "args": {"send_to_phone": {"as_document": "true"}}, "history": WEATHER_CHAT},
    {"say": "write a short report about electric cars as a word document and send it to me",
     "tools": [["research_report", "create_word_document"], "send_file"]},

    # --- lights & music ------------------------------------------------------------------------
    {"say": "turn the lights off", "tools": ["lights"], "args": {"lights": {"power": "off"}}},
    {"say": "can you make the bedroom light blue", "tools": ["lights"],
     "args": {"lights": {"color": "blue", "light": "bedroom"}}},
    {"say": "it's too bright in here, dim the lamp a bit", "tools": ["lights"]},
    {"say": "turn off the lights at 11pm every night", "tools": ["create_routine"], "forbid": ["lights"]},
    {"say": "play janice stfu by drake", "tools": ["music_play"],
     "args": {"music_play": {"query": "janice"}}},
    {"say": "put on some relaxing jazz", "tools": ["music_play"], "forbid": ["youtube_play"]},

    # --- the internet ---------------------------------------------------------------------------
    {"say": "what's the weather today", "tools": ["weather"], "reply": r"16|°"},
    {"say": "do I need an umbrella tomorrow", "tools": ["weather"]},
    {"say": "what's the weather like in Paris this weekend", "tools": ["weather"],
     "args": {"weather": {"place": "paris"}}},
    {"say": "What is a mcp server", "tools": ["research"],
     "reply": r"(?i)model context protocol", "reply_not": r"(?i)master control"},
    {"say": "do a research on MCP servers", "tools": ["research"],
     "reply": r"https://(modelcontextprotocol\.io|mcpservers\.org)"},
    {"say": "who won the champions league final this year", "tools": ["research"]},
    {"say": "what's the price of bitcoin right now", "tools": ["research"]},
    {"say": "what's the weather today", "spoken": True, "tools": ["weather"], "max_chars": 300,
     "reply_not": r"https?://"},
]
