title: Running the site
summary: The staff dashboard, approving submissions, giving people access to trips, and importing the catalogue from spreadsheets.
audience: staff
section: Staff
order: 10
updated: 2026-10-27

# Running the site

For staff. Open **Staff dashboard** from your account menu (top right).

## The staff dashboard

The dashboard shows the site's numbers and a **needs attention** list, most urgent first. Each entry links to where you fix it:

| Entry | What to do |
| --- | --- |
| **Submissions waiting for review** | Approve or reject them in the approval queue. Overdue ones (past the review target) are marked. |
| **Role requests** | People asking to become a vendor or content provider. Approving adds them to the group. |
| **Reported reviews** | Keep or hide each review, then mark its reports resolved. A review with 3 open reports is already hidden. |
| **Events with a city that isn't in the catalogue** | Link each to a city, or create the city. |
| **Cities without a region**, **Cities whose region is in a different country** | Fix them in the admin. |
| **Yearly activities with no upcoming dates** | Add next year's event ("Add <year> dates" on the last one). |
| **Activities whose place isn't linked** | Pick the country and city on the activity. |
| **HEIC images most browsers can't show**, **Accounts with a placeholder email**, **Legal pages still have placeholders** | Re-upload, set a real email, or fill in the legal details. |

## Approving submissions

New activities, events and places from members wait in the approval queue (linked from **Submissions waiting for review**). Approve, reject, or ask for changes; the member is notified. Approved items are public at once.

Restaurants, cafés, bars and markets use the **Food & drink** place type. Approve only notable ones: places people travel for (a famous market, a beer hall, a bucket-list restaurant). Turn down everyday lunch spots; a trip's meals work fine as typed text, and catalogue opening hours go stale.

## Access to trips

Trip access is per person and per trip, set in the admin:

- **Give someone access to a trip**: on the trip in the admin, add a trip grant for the person, with their role (viewer, commentor or editor). They're notified.
- **Let someone create trips**: on the person in the admin, give them the **creator** role. Anyone can still start a trip from a bucket-list goal.
- **Remove access**: delete the grant.

Staff see every trip, with no grant needed. See [sharing and access](/help/sharing-and-access/) for what each role can do.

## Importing and exporting the catalogue

**Import CSV** on the staff dashboard opens **Import from CSV**, which adds or updates countries, regions, cities, places, activities or events from a spreadsheet.

1. Pick **What are you importing?** and upload the **CSV file**. Import in this order, since each looks up the ones before it: countries, regions, cities, places, activities, events.
2. Click **Preview import**. Each row shows **New**, **Update** or **Error**; "Nothing has been saved yet."
3. Click **Import N rows** (rows with errors are skipped), or **Cancel**. When nothing can be imported, the page offers **Upload a corrected file** instead.

Dates are month/day/year, like 9/18/2027 (how Excel shows them); 2027-09-18 works too, but day-first dates such as 18/9/2027 are refused. Times are 20:00 or 8:00 PM.

A **blank template** shows the columns; **export what's loaded now** downloads the published items in the same columns, ready to edit and import again. Imported items are published straight away.

## Country flags

Every country's picture is its flag, shown whole (never cropped) on its page, in the country list, on shared links and on any activity or event card that has no picture of its own. A new country gets its flag when it's added (on the site, by CSV import or by the seed command). On a country's **Edit** page, choosing an image makes it the picture instead; **Use the flag** puts the flag back.

For the countries already on the site, the `country_flags` command (run on the server; `--dry-run` first lists what it would change, `--country DE` does one) makes each flag the picture. A photo a country had stops being its picture but isn't deleted, and the command lists those countries.

## Nightly counts

"Members who've been", "On trips" and badges are recounted automatically, once a night. If a count looks wrong after fixing data, ask whoever runs the server to run the recount.

## Problems

| Problem | What to do |
| --- | --- |
| A member can't see a trip | Check they have a grant on it. |
| A member has no **New trip** button | Give them the creator role, or point them to **Plan a trip** on a goal. |
| An import row says **Error** | Fix that row (the details say why) and upload the corrected file. |
