# LuGroupLib user guide

Everything you can do with the website and the sync client. If you haven't set up your
machine yet, do [KiCad setup](SETUP_KICAD.md) first — it takes about ten minutes and you
only do it once.

**Contents**

1. [The idea in one minute](#the-idea-in-one-minute)
2. [Signing in](#signing-in)
3. [Browsing and searching](#browsing-and-searching)
4. [Libraries](#libraries)
5. [Adding a part](#adding-a-part)
6. [Adding a part from a Mouser link](#adding-a-part-from-a-mouser-link)
7. [Editing, deprecating, deleting](#editing-deprecating-deleting)
8. [Inventory](#inventory)
9. [Stocking from a Mouser order](#stocking-from-a-mouser-order)
10. [The downloader](#the-downloader)
11. [Using the library in KiCad](#using-the-library-in-kicad)
12. [Common questions](#common-questions)

---

## The idea in one minute

The website is where parts are **managed**. KiCad is where they're **used**. The sync
client is what carries changes from one to the other.

Nothing you do on the website appears in KiCad until you sync. Nothing you do in KiCad
affects the website at all — it's a one-way flow, by design, so nobody can accidentally
change the shared library from a schematic.

---

## Signing in

Click **Sign in** and authorise with your lab Slack account. That's the whole account
system: if you're in the workspace, you're in the library.

**Browsing is open to everyone** — you don't need to sign in to search parts or check
stock. You need to sign in to add or change anything.

Your role, if you have one:

- **Member** — the default. Add parts to common libraries, and to sub-group libraries
  you've been added to.
- **Master librarian** — can edit every part and every library. Shown with a ★ next to
  your name. Ask an existing librarian if you need this.

---

## Browsing and searching

The **Browse** page lists every part in every library. Everyone can see everything;
permissions only govern who can *change* things.

- The search box matches MPN, value, description, manufacturer, keywords, and name.
- The **library** and **category** dropdowns narrow the list.
- Clicking a row opens the part, which shows its full metadata, its stock, its permanent
  KiCad identifier, and who added it.

---

## Libraries

A library is both an organisational unit and a permission boundary. Each one appears in
KiCad's Symbol Chooser as its own entry under `LuGroupLib_DB`.

There are two kinds, and you choose which when you create it:

| | **Sub-group** | **Common** |
|---|---|---|
| Who can add parts | Owner and members only | Anyone signed in |
| Who can edit a part | Owner, members, librarians | Its uploader, people they invite, librarians |
| Good for | A specific project team | Shared jellybean parts everyone uses |

### Creating one

**Libraries → New library.** The name is the important decision, because it becomes part
of every part's permanent identifier — a part in `RF_Frontend` is
`LuGroupLib:RF_Frontend/<part>` in every schematic that uses it.

- Letters, numbers, and `_ . + -` only. No spaces, no `/`, no `:`.
- **The name locks once the library holds its first part.** Until then you can rename or
  delete it freely; afterwards both are blocked, because renaming would break the link
  from every schematic symbol placed from it.
- So pick something durable — tied to what the group *does*, not to a person, a grant, or
  a project that will be renamed. `RF_Frontend` ages better than `Chen_NSF_2026`.

The creation page shows you a live preview of what your parts' identifiers will look
like. Use it.

### Adding members

Open a sub-group library and use **Add member**. Members can add parts and edit anything
in that library. Common libraries have no member list — anyone can contribute, and each
part carries its own editor list instead.

---

## Adding a part

**Upload part**, or the button on a library page.

| Field | Notes |
|-------|-------|
| **Library** | Which library it goes in. You'll only see ones you can add to. |
| Category, MPN, Manufacturer, Value | Metadata. Category and MPN show in KiCad's chooser. |
| Description, Datasheet, Keywords | Keywords are what people search for — be generous. |
| **Symbol** (required) | A `.kicad_sym` file. |
| Footprint | A `.kicad_mod` file. Optional but strongly recommended. |
| 3D model | `.step`, `.stp`, or `.wrl`. Auto-linked to the footprint. |

Only the symbol is mandatory, but a part without a footprint is half a part — whoever
uses it will have to pick one themselves, and they may not pick the same one you would.

After saving you'll get the part page, showing its permanent KiCad identifier. **Sync to
see it in KiCad.**

---

## Adding a part from a Mouser link

Faster than filling the form by hand, and better at metadata.

1. **Upload part → Add from Mouser link** (or go straight to `/upload/from-mouser`).
2. Paste a Mouser product URL — or just the part number.
3. You get the normal upload form, prefilled.

What comes from where matters:

- **Mouser** provides MPN, manufacturer, description, datasheet link, stock, and price.
  These are copied exactly.
- **AI** drafts the category, search keywords, the component value, and — if it's
  confident — suggests a footprint from ones already in your library. These are tagged
  **AI** on the form.
- **You** attach the symbol. Mouser doesn't publish KiCad symbols, so this step is always
  manual.

**Nothing is saved until you submit the form.** Check the AI-tagged fields, especially a
suggested footprint: a wrong footprint is a scrapped board, so it's a suggestion, never a
decision. If the model wasn't confident it suggests nothing rather than guessing.

If AI isn't configured on your server, lookup still works — you just fill in the category
and keywords yourself.

---

## Editing, deprecating, deleting

Open a part and click **Edit**, if you have permission. If you don't, the page tells you
who does.

Everything on the edit form is safe to change. The part's KiCad identifier is fixed at
creation and never changes, so renaming a part — or fixing a typo in its description —
can't break a schematic that already uses it.

### Deprecating vs deleting

**Deprecate** (a checkbox on the edit form) hides a part from KiCad's Symbol Chooser
while leaving it in the database. Schematics that already use it keep working. This is
the right way to retire a part.

**Delete** removes it entirely. Any schematic that already placed it loses its library
link. Only do this for genuine mistakes — a part added twice, or one nobody ever used.

### Moving a part between libraries

You can't, and that's deliberate. A part's library is part of its permanent identifier,
so moving it would orphan it in every schematic that uses it.

If a part in a sub-group library turns out to be generally useful, **re-create it in the
common library and deprecate the original**. Existing designs keep working, new ones pick
up the common copy.

---

## Inventory

The **Inventory** page lists every part with its stock count, storage location, and
reorder level.

- **Anyone signed in can adjust stock.** Taking parts off a shelf is something everyone
  does; if logging it were a privilege it would stop happening.
- Every adjustment records who made it, when, and why. The history is on the part page.
- Stock can't go negative — if it would, the count is wrong somewhere and you'll get an
  error rather than a silently clamped zero.

### Setting up a part for tracking

On the part page, set:

- **Storage location** — e.g. `Drawer B3`. Free text; use whatever scheme the lab uses.
- **Reorder level** — you'll get a low-stock warning at or below this. Leave it at 0 for
  parts you don't want to track.

### Stock in KiCad

After a sync, **In Stock** and **Location** appear as columns in KiCad's Symbol Chooser.
That's the main reason to bother tracking inventory: the moment you want to know whether
you have a part is while you're choosing it.

---

## Stocking from a Mouser order

When an order arrives:

1. **Inventory → Stock from a Mouser order.**
2. Upload the order confirmation PDF, or paste the text of the confirmation email.
3. You get a review table: each line, the part it matched, and what the stock would
   become.
4. Untick anything you don't want, then confirm.

**Nothing moves until you confirm.** Lines that don't match a part in the library are
flagged rather than guessed at — add the part first (the Mouser link flow is quickest),
then re-read the order.

Every applied line is logged against the order number, so you can trace a count back to
the order that produced it.

---

## The downloader

The downloader — the sync client — copies the library to your machine. It's the only way
parts get into KiCad.

### Three ways to run it

| | How | When |
|---|---|---|
| **`sync.bat`** | Double-click it in `client/` | Windows, the usual way |
| **KiCad plugin** | ⤓ toolbar button in the PCB editor | Without leaving KiCad |
| **Command line** | `python sync_client.py` | macOS, Linux, or scripting |

### What it reports

```
OK - 2 new, 1 updated (41.2 KB transferred, 84 unchanged)
```

It only transfers what actually changed. A sync with nothing new moves zero bytes and
says **"Already up to date."** The first sync on a machine downloads everything.

### After syncing

- **New or changed symbols:** Symbol Chooser → **Refresh** (the ↻ button).
- **New footprints or 3D models:** **restart KiCad.** Footprint libraries are cached and
  the chooser refresh doesn't reload them. This catches everyone once.

### Sync tokens

The sync client authenticates with a token, not your Slack session.

1. **Sync tokens** in the top nav → **Create token**.
2. Label it after the machine (`lab desktop`, `personal laptop`).
3. Copy it immediately — it's stored hashed and never shown again.
4. Paste it into `client_config.json`, or let `install.py` do it.

Make one per machine. Then losing a laptop means revoking one token instead of resetting
everyone's.

### If sync fails

| Message | Meaning |
|---------|---------|
| `the server rejected your sync token` | Token revoked or mistyped. Create a new one. |
| `401` | No token at all in `client_config.json`. |
| Connection refused / timeout | Server down, or you're off the network it's on. |

---

## Using the library in KiCad

Press `A` in the schematic editor. Under **`LuGroupLib_DB`** you'll find one entry per
library — `General`, plus your lab's sub-groups. Parts show their MPN, manufacturer,
category, and stock.

Place one and it arrives with its footprint already assigned and its 3D model linked.

You'll also see a plain `LuGroupLib` library in the list. That's the underlying symbol
storage that the database library reads from — ignore it and use `LuGroupLib_DB`.

---

## Common questions

**Do I need to sync after every change someone makes?**
Only when you want their changes. Sync before starting a design, and again if someone
tells you they've added a part you need.

**Can I edit the library files in `Documents/KiCad_LuGroupLib` directly?**
No — the next sync overwrites them. The website is the only place to make changes. (If
you do edit or corrupt something, sync will detect it and restore the correct version.)

**Someone deleted a part I was using. What happens?**
Your schematic keeps the symbol it already placed, but the library link breaks. Ask
whoever deleted it to re-add it — this is exactly why deprecating is preferred.

**Why can't I edit a part in a common library?**
Common libraries let anyone *add*, but each part stays with its uploader. Ask them to
invite you — there's an invite control on the part page — or ask a master librarian.

**Why is my new library missing from KiCad?**
Sync. New libraries arrive in the sync bundle; nothing needs reconfiguring locally.

**The library shows in KiCad but has no parts.**
The SQLite ODBC driver isn't installed or is named wrong. See
[KiCad setup, step 1](SETUP_KICAD.md#1-install-the-sqlite-odbc-driver).
