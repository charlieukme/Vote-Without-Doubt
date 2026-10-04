import os
import random
from datetime import datetime
from app.extensions import db
from app.models import BallotRecord as Ballot

class Relayer:
    def process_queue(self, batch_size: int = 10):
        queued = Ballot.query.filter_by(state='QUEUED').order_by(Ballot.id.asc()).all()
        # shuffle independent ballots for privacy
        items = list(queued)
        random.shuffle(items)
        for b in items[:batch_size]:
            b.state = 'SUBMITTED'
            db.session.commit()
            b.tx_hash = '0xstub'
            b.block_number = 0
            b.state = 'CONFIRMED'
            db.session.commit()
            b.state = 'FINALIZED'
            db.session.commit()
