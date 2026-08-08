# Integration with Konwencik system

Export scheduled sessions to google sheet.

Columns (no configuration because Konwencik has its format):

- id: Session.id
- day: Day when session is scheduled (date format, like 09.02.2024)
- start: session starting hour (10:00)
- end: session ending hour (11:50)
- title: Session.title
- description: Session.description
- speaker: Session.display_name
- room: Space.name
- room_position: empty
- block: track name
- type: proposal category
- photo_url: empty, allow overwriting with session field with external image
  url (configure)
- icon: configurable per category, allow overwriting with an icon name session
  field (configure)
- icon_background_color: configurable per track (for sessions with multiple
  tracks ordering chooses)
