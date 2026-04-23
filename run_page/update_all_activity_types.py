"""
Update activity types for all matching COM-CN activities.
Updates badminton, table_tennis, and other supported types.
"""
import asyncio
import os
import sys
from datetime import datetime

current = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, current)

from garmin_sync import restore_or_login, Garmin
from garmin_cn_garth import GarminCngarthClient
from activity_type_map import map_com_type_to_cn


async def main():
    print('='*60)
    print('Updating ALL activity types with new mapping')
    print('='*60)
    
    # Load env
    from dotenv import load_dotenv
    load_dotenv('.temp_garmin.env')
    
    com_username = os.getenv('GARMIN_COM_USERNAME')
    com_password = os.getenv('GARMIN_COM_PASSWORD')
    cn_username = os.getenv('GARMIN_CN_USERNAME')
    cn_password = os.getenv('GARMIN_CN_PASSWORD')
    
    # Login to COM
    print('Logging into Garmin COM...')
    com_client = restore_or_login(com_username, com_password, False)
    garmin_com = Garmin(com_client, 'COM', False)
    print('COM login OK')
    
    # Login to CN
    print('Logging into Garmin CN...')
    cn_client = GarminCngarthClient(cn_username, cn_password, is_cn=True)
    cn_client.login()
    garmin_cn = Garmin(cn_client, 'CN', False)
    print('CN login OK')
    
    # Get CN activity types
    cn_types = await asyncio.to_thread(cn_client.get_activity_types)
    cn_types_dict = {t['typeKey']: t for t in cn_types}
    print(f'CN supports {len(cn_types)} activity types')
    
    # Get COM activities (up to 300)
    print()
    print('Fetching COM activities (up to 300)...')
    com_activities = []
    for offset in range(0, 300, 100):
        activities = await garmin_com.get_activities(offset, 100)
        if not activities:
            break
        com_activities.extend(activities)
        print(f'  Fetched {len(com_activities)} activities...')
    print(f'Total COM activities fetched: {len(com_activities)}')
    
    # Count activities that need updating
    print()
    print('Activities that can be mapped:')
    target_types = ['soccer', 'squash', 'badminton', 'table_tennis', 'tennis', 'walking', 'running']
    for t in target_types:
        count = sum(1 for a in com_activities 
                   if a.get('activityType', {}).get('typeKey') == t)
        if count > 0:
            cn_type = map_com_type_to_cn(t)
            print(f'  {t}: {count} activities -> CN: {cn_type}')
    
    # Process each activity
    print()
    print('Updating activity types...')
    updated = 0
    skipped = 0
    not_found = 0
    
    for act in com_activities:
        act_id = act.get('activityId')
        act_name = act.get('activityName', '')
        com_type = act.get('activityType', {}).get('typeKey', 'unknown')
        start_time = act.get('startTimeGMT', '')
        
        # Map to CN type
        cn_type_key = map_com_type_to_cn(com_type)
        
        # Skip if mapped to 'other' (not supported in CN)
        if cn_type_key == 'other':
            skipped += 1
            continue
        
        if not start_time:
            skipped += 1
            continue
        
        # Find matching CN activity by start time
        try:
            start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            date_str = start_dt.strftime('%Y-%m-%d')
            
            # Search CN activities
            found = False
            for offset in [0, 100, 200, 300]:
                recent = await garmin_cn.get_activities(offset, 100)
                if not recent:
                    break
                
                for cn_act in recent:
                    cn_start = cn_act.get('startTimeGMT', '')
                    if cn_start and date_str in str(cn_start):
                        cn_act_id = cn_act.get('activityId')
                        cn_current_type = cn_act.get('activityType', {}).get('typeKey', '')
                        
                        if cn_type_key != cn_current_type:
                            # Find CN type ID
                            type_info = cn_types_dict.get(cn_type_key)
                            if type_info:
                                type_id = type_info.get('id')
                                parent_id = type_info.get('parentId')
                                await asyncio.to_thread(
                                    cn_client.update_activity_type,
                                    cn_act_id,
                                    cn_type_key,
                                    type_id,
                                    parent_id
                                )
                                print(f'  [{act_id}] {act_name}: {cn_current_type} -> {cn_type_key}')
                                updated += 1
                            else:
                                print(f'  [{act_id}] {act_name}: CN type "{cn_type_key}" not found')
                        found = True
                        break
                
                if found:
                    break
            
            if not found:
                not_found += 1
                
        except Exception as e:
            print(f'  Error processing {act_id}: {e}')
            skipped += 1
        
        await asyncio.sleep(0.3)  # Rate limit
    
    print()
    print(f'Results:')
    print(f'  Updated: {updated}')
    print(f'  Skipped (not in target types or mapped to other): {skipped}')
    print(f'  Not found in CN: {not_found}')


if __name__ == '__main__':
    asyncio.run(main())
