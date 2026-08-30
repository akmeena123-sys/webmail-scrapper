#!/usr/bin/env python3
import sqlite3
from datetime import datetime
import scraper
import os

DB = os.path.join(os.path.dirname(__file__), 'data.db')

def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT id, subject, sender, snippet, category, assigned_to FROM emails ORDER BY date ASC')
    rows = cur.fetchall()
    if not rows:
        print('No rows found')
        return

    staff = scraper.parse_workorder()
    if not staff or len(staff) < 2:
        staff = ['Vipin','Sunil','Rajeev','Anil','Hemraj']

    updates = 0
    changed = []
    i = 0
    for r in rows:
        eid, subj, sender, snippet, old_cat, old_assigned = r
        subj = subj or ''
        snippet = snippet or ''
        sender = sender or ''
        lower_txt = (subj + ' ' + snippet + ' ' + sender).lower()

        # verification/delivery -> Miscellaneus + On File
        if any(kw in lower_txt for kw in ['email verification', 'verification', 'delivery report', 'mail delivery', 'successful mail delivery', 'delivery-status']):
            new_cat = 'Miscellaneus'
            new_assigned = 'On File'
            new_pri = 0
        else:
            if scraper.is_pccit_jaipur(sender):
                new_cat = 'PCCIT'
                new_pri = 0
                # assignment: try subject match
                matched = scraper.assign_by_subject(subj, snippet, staff)
                if matched:
                    new_assigned = matched
                else:
                    new_assigned = staff[i % len(staff)]
                    i += 1
            elif scraper.is_delhi_sender(sender):
                new_cat = 'Additional office'
                new_pri = 1
                matched = scraper.assign_by_subject(subj, snippet, staff)
                if matched:
                    new_assigned = matched
                else:
                    new_assigned = staff[i % len(staff)]
                    i += 1
            elif scraper.is_additional_sender(sender):
                new_cat = 'Additional office'
                new_pri = 0
                matched = scraper.assign_by_subject(subj, snippet, staff)
                if matched:
                    new_assigned = matched
                else:
                    new_assigned = staff[i % len(staff)]
                    i += 1
            else:
                new_cat = scraper.categorize(subj, snippet)
                matched = scraper.assign_by_subject(subj, snippet, staff)
                if matched:
                    new_assigned = matched
                else:
                    new_assigned = staff[i % len(staff)]
                    i += 1
                # priority default 0
                new_pri = 0

        if new_cat != (old_cat or '') or new_assigned != (old_assigned or ''):
            try:
                cur.execute('UPDATE emails SET category=?, assigned_to=?, priority=? WHERE id=?', (new_cat, new_assigned, int(bool(new_pri)), eid))
                updates += 1
                changed.append((eid, old_cat, new_cat, old_assigned, new_assigned, new_pri))
            except Exception as e:
                print('update failed for', eid, e)

    conn.commit()
    conn.close()

    print(f'Processed {len(rows)} rows, applied {updates} updates')
    if changed:
        print('Sample changes:')
        for c in changed[:20]:
            print(c)

if __name__ == '__main__':
    main()
