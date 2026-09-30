import csv
import json
import re
from pathlib import Path


FIELDS = [
    "company_name",
    "booth",
    "description",
    "email",
    "mobile_primary",
    "domain",
    "full_address",
    "city",
    "linkedin_url",
]

# Transcribed from the two supplied Nxtbook exhibitor-list screenshots
# (pages 28 and 30).  Websites are retained only where legible in the images.
ENTRIES = [
    ("3M Peltor & Scott", "1244", "https://www.3m.com/wearablesafety"),
    ("4C North America", "423", ""),
    ("A&S, Inc.", "2054", ""),
    ("Advanced Government Logistics, Inc.", "1254", ""),
    ("Advanced Technology Systems Company", "2747", ""),
    ("Aerial", "418", ""),
    ("Aeroflow LLC", "2751", ""),
    ("AeroVironment (AV)", "2235", "https://www.avinc.com"),
    ("AEDIC", "2255", "https://www.aev.com"),
    ("Afterburner WTS", "2915", "https://www.afterburnerwts.com"),
    ("Air Supply Tools", "1149", "https://airsupplytools.com"),
    ("AIRBUS U.S. Space & Defense, Inc.", "1457", "https://www.airbusus.com"),
    ("Alders Aerospace", "558", "https://aldersaerospace.com"),
    ("AM General", "2007", "https://www.amgeneral.com"),
    ("Amazon Web Services", "1150", "https://aws.amazon.com/defense"),
    ("Amentum", "1407", "https://www.amentum.com"),
    ("American Rheinmetall", "1907", "https://www.rheinmetall-us.com"),
    ("Americans in War & Peace Experience", "1983", "https://americansinwarzone.org"),
    ("Ametrine, Inc.", "1349", "https://ametrine.com"),
    ("Andar Electromechanical Systems", "544", ""),
    ("Anduril", "1328", "https://www.anduril.com"),
    ("Angeles Without Wings, Inc. / Animals In War & Peace", "1569", "https://animalsinwarandpeace.org"),
    ("Anj... LLC", "1283", ""),
    ("Appian Corporation", "2350", "https://appian.com/defense"),
    ("Applied Inclusion", "781", ""),
    ("Artec Associates", "848", "https://artec.com"),
    ("Armag Corporation", "1963", ""),
    ("ASEPTICO", "2042", "https://www.aseptico.com"),
    ("Aspen Water Inc.", "2806", "https://www.aspenwater.com"),
    ("BAE Systems", "2527", "https://www.baesystems.com"),
    ("BAE Systems Ordnance", "429", ""),
    ("Bacon Hunter", "2846", "https://baconhunter.com"),
    ("Battle Road Digital", "843", "https://battleroad.digital"),
    ("Battlefield International Inc.", "2813", ""),
    ("Battlespace Simulations, Inc.", "557", "https://www.bsimulations.com"),
    ("Bauer Compressors, Inc.", "620", "https://www.bauercompressors.com"),
    ("BeverFit", "1211", "https://www.beverfitusa.com"),
    ("Beri", "946", ""),
    ("Blue Cross Blue Shield Association", "1463", "https://www.fepblue.org"),
    ("Bluesky Innovations", "1507", "https://www.blueskyinnovations.com"),
    ("BMC Helix", "1418", ""),
    ("Boeing", "1737", "https://www.boeing.com"),
    ("Booz Allen Hamilton", "2843", "https://www.boozallen.com"),
    ("Boresight USA", "1261", ""),
    ("Boulevard Labs", "545", "https://www.boulevardlabs.ai"),
    ("Bounos Imaging", "2913", ""),
    ("Boxhead", "2807", ""),
    ("Breakthrough Clean Technologies", "2850", "https://breakthroughclean.com"),
    ("Briar-Tronics Inc.", "2553", "https://www.briar-tronics.com"),
    ("Bunker Supply", "1319", "https://bunkersupply.us"),
    ("C.E. Niehoff & Co.", "1155", "https://www.ceniehoff.com"),
    ("CACI International Inc.", "0025", "https://www.caci.com"),
    ("Cambridge Pixel", "2361", "https://www.cambridgepixel.com"),
    ("Carahsoft Technology Corp.", "1144", "https://www.carahsoft.com"),
    ("Case Knives (W.I.L. Distribution)", "2560", ""),
    ("Catoma Gear, Inc.", "441", "https://www.catoma.com"),
    ("CDO", "1765", ""),
    ("CEIA USA", "818", "https://www.ceiausa.com"),
    ("Chimney Trail Health", "451", "https://www.chimneytrailhealth.com"),
    ("CISCO", "1420", "https://www.cisco.com"),
    ("Claroty", "2302", "https://claroty.com"),
    ("CMB Networks", "607", "https://cmbnetworks.org"),
    ("Colt's Manufacturing Company LLC", "2355", "https://www.colt.com"),
    ("Columbia Southern University", "2163", "https://www.columbiasouthern.edu"),
    ("Command Holdings Group/DM", "1554", "https://www.commandholdings.com"),
    ("Commtel Enterprises, Inc.", "512", "https://commtelinc.com"),
    ("Compultech Inc.", "1875", "https://compultech.com"),
    ("Comrod Inc.", "1207", "https://www.comrod.com"),
    ("Contact Corporation", "2321", ""),
    ("Corelight", "2843", "https://corelight.com"),
    ("Cubic Defense", "1807", "https://www.cubic.com/defense"),
    ("Curtiss-Wright", "1513", "https://www.curtisswrightds.com"),
    ("C2", "1249", ""),
    ("Cygnus Tech", "1558", ""),
    ("Cystic Fibrosis Foundation", "1337", "https://www.cff.org"),
    ("Cyber Defense Technologies", "1248", ""),
    ("Cylance", "546", ""),
    ("Datalinks, Inc.", "1210", ""),
    ("Danner", "1244", "https://www.danner.com"),
    ("Dantem Cooling, Inc.", "2280", ""),
    ("Darley Defense", "1449", "https://www.darley.com/how-we-serve/defense"),
    ("Davis Defense Group, Inc.", "2807", "https://davisdefense.com"),
    ("Decision Lens", "2960", "https://decisionlens.com"),
    ("Defense Suicide Prevention Office", "1288", "https://www.dspo.mil"),
    ("Dell Technologies", "1713", "https://www.dell.com/federal"),
    ("Deschamps Mats Systems Inc.", "2080", ""),
    ("DRIFIRE X Wild Things", "1457", "https://www.drifire.com"),
    ("DripDrop Hydration", "1458", "https://dripdrop.com"),
]


def main():
    records = [
        dict(
            zip(
                FIELDS,
                [name, booth, "", "", "", domain, "", "", ""],
            )
        )
        for name, booth, domain in ENTRIES
    ]
    records.sort(key=lambda row: (int(row["booth"]), row["company_name"].casefold()))
    output = Path(__file__).parent / "output"
    output.mkdir(exist_ok=True)
    with (output / "MODERN_DAY_MARINE_2026_exhibitors.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    with (output / "MODERN_DAY_MARINE_2026_exhibitors.json").open(
        "w", encoding="utf-8"
    ) as stream:
        json.dump(records, stream, ensure_ascii=False, indent=2)
    print("=== Verification Report: Modern Day Marine 2026 ===")
    print(f"Total Screenshot Records : {len(records)}")
    print(f"Booth Coverage           : {sum(bool(x['booth']) for x in records)}/{len(records)}")
    print(f"Website Coverage         : {sum(bool(x['domain']) for x in records)}/{len(records)}")
    print("Source Verified          : supplied Nxtbook screenshots, pages 28 and 30 [OK]")


if __name__ == "__main__":
    main()
