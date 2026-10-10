# Example problems for every case

All of these are invented. Two ways to use them:

1. **Report form examples.** On *Report a problem*, choose a category and tap one of the "For example" lines to start from it (the list below shows
   the same text).
2. **Sample complaints in every situation.** Sign in as the coordinator (`admin`), open **Projects** on a fresh install and press **Create sample works and
   complaints here**. It creates the example complaints below around the place you choose and lists each one's reference and tracking code (shown once).
   From the command line: `python seed.py --reset --scenario LAT LNG`.

## A. One example per category (what the form suggests)

| Category | Goes to | Example |
|---|---|---|
| Water leak or pipe problem | Water Department | "A pipe has burst outside the market and water is flooding the road." / "Tap water has been brown with very low pressure since yesterday." |
| Electrical fault, street light or cable | Power Department | "The street light has been out for a week and a cable is hanging low near the bus stop." / "The transformer near the school gate is sparking when it rains." |
| Telephone or internet cable problem | Telecom Department | "A telephone cable has fallen across the lane and vehicles are catching it." / "The cable duct cover is open and cables are lying exposed on the footpath." |
| Road surface damage or pothole | Roads Department | "A large pothole at the junction that two-wheelers keep swerving around." / "The road sank after the pipe repair and now collects water." |
| Safety hazard | Coordinator (high priority) | "An open trench with no barrier or warning sign beside the footpath." / "A manhole cover is missing right next to the bus stop." |
| Work happening without notice | Coordinator | "A crew started digging at night with no notice board or permit displayed." |
| Work taking too long | Coordinator | "The trench has been open for three weeks and nobody is working on it." |
| Noise, dust or disruption | Coordinator | "Drilling starts at 6 a.m. every day and dust is covering the shops." |
| Something else | Coordinator | "Building material was left on the road after the work finished." |

## B. The sample complaints: one for each situation

| # | Situation | What you will see | Try this |
|---|---|---|---|
| 1 | **New, untouched** (water leak outside the market) | Normal priority, "Received" | As `water.dept`: acknowledge it |
| 2 | **Same problem reported 4 times** (hanging electrical cable at a bus stop) | One problem, **Urgent**, "4 people reported the same problem" | As `power.dept`: update it once and all four reporters are told |
| 3 | **Acknowledged** (fallen telephone cable) | "Acknowledged", no date promised | As `telecom.dept`: promise a time |
| 4 | **Work under way, promise on track** (pothole at a junction) | "Promised by 13 Nov 2026 (within 5 days), 5 days left" | As admin: *Advance simulated time* by 6 days and watch it escalate |
| 5 | **Promise missed, with the head of department** (brown tap water) | **High priority**, "With the head of the Water Department", ordinary staff cannot act | Sign in as `water.head` to act on it |
| 6 | **Missed again: with the coordinator** (sparking transformer) | **Urgent**, "With the coordinator" | As `admin` or `power.head`: resolve it |
| 7 | **Resolved, waiting for the resident** (road sank after pipe repair) | "Marked resolved: please confirm" | As a resident: *Track a complaint* with its code, then "Yes, it is fixed" or "No, it is not fixed" |
| 8 | **Reopened by the resident** (loose duct cover) | "Reopened: not fixed", raised priority, back with Telecom | As `telecom.dept`: promise a new time |
| 9 | **Confirmed fixed** (flickering street light) | "Confirmed fixed", shown as fixed on the public map | Look at the home screen's grievance box |
| 10 | **Closed without action** (neighbour's private tank) | "Closed without action" with the reason | Track it with its code |
| 11 | **Unrouted safety hazard** (open trench) | High priority, waiting in the coordinator's queue | As `admin`: send it to Roads |
| 12 | **Unrouted: work without notice** | Coordinator's queue | As `admin`: assign it |
| 13 | **Unrouted: work taking too long** | Coordinator's queue | as above |
| 14 | **Unrouted: noise and dust** | Coordinator's queue | as above |
| 15 | **Unrouted: something else** | Coordinator's queue | as above |

Accounts are in `backend/DEMO_CREDENTIALS.md`. Departments only ever see their own category (Power cannot see the water leak, and so on); the
coordinator sees everything.

## C. A short script to see duplicates and escalation yourself

1. As a resident, report *Electrical* with the example "The street light has been out for a week and a cable is hanging low near the bus stop" and pin a spot.
2. Report the same category again at (almost) the same spot, two more times: the priority climbs to High, then Urgent, and the first reporter gets "More
   people reported this same problem" in their history.
3. Sign in as `power.dept`, open **Complaints**, choose "Promise a resolution time", enter 5 days.
4. Sign in as `admin`, open **Work and checks** and advance simulated time by 6 days.
5. As `power.dept` you can no longer act; as `power.head` you can. The resident sees "escalated to the head of the Power Department".
