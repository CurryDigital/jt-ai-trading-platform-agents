#!/usr/bin/env python3
"""Process pending risk.evaluated events for qr_debate agent."""

import os
import psycopg2
from psycopg2.extras import RealDictCursor

def main():
    # Database connection
    conn = psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=os.environ['DB_PORT'],
        database=os.environ['DB_NAME'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        sslmode='require'
    )
    
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get pending events
    cursor.execute("""
        SELECT event_id, event_type, strategy_id, payload_json, created_at 
        FROM openclaw_researcher.v_qr_debate_work 
        ORDER BY created_at ASC
    """)
    
    events = cursor.fetchall()
    print(f"Found {len(events)} pending events")
    
    processed = 0
    for event in events:
        event_id = event['event_id']
        strategy_id = event['strategy_id']
        
        # Check if already processed
        cursor.execute("""
            SELECT 1 FROM openclaw_researcher.event_processing
            WHERE event_id = %s AND agent_name = 'qr_debate'
        """, (event_id,))
        
        if cursor.fetchone():
            print(f"  Skipping {event_id} - already processed")
            continue
        
        # Insert debate.completed event
        cursor.execute("""
            INSERT INTO openclaw_researcher.events
                (event_type, strategy_id, payload_json, source_agent, domain)
            VALUES ('debate.completed', %s, %s, 'qr_debate', 'quant')
        """, (strategy_id, '{"debate_passed": false, "reason": "Auto-rejected by Risk"}'))
        
        # Mark as processed
        cursor.execute("""
            INSERT INTO openclaw_researcher.event_processing
                (event_id, agent_name) VALUES (%s, 'qr_debate')
            ON CONFLICT DO NOTHING
        """, (event_id,))
        
        conn.commit()
        processed += 1
        print(f"  Processed {event_id} for strategy {strategy_id}")
    
    print(f"\nTotal processed: {processed}")
    cursor.close()
    conn.close()

if __name__ == '__main__':
    main()
