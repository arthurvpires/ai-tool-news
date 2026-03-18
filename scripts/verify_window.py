from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
SEND_HOUR_START = 8
SEND_HOUR_END_WEEKDAY = 22

def test_logic(test_dt):
    is_weekend = test_dt.weekday() >= 5
    in_window = (SEND_HOUR_START <= test_dt.hour < SEND_HOUR_END_WEEKDAY)
    return is_weekend, in_window

# Test cases
tests = [
    (datetime(2026, 3, 18, 10, 0), "Wednesday 10am"),
    (datetime(2026, 3, 18, 3, 0), "Wednesday 3am (Madrugada)"),
    (datetime(2026, 3, 18, 21, 59), "Wednesday 9:59pm"),
    (datetime(2026, 3, 18, 22, 0), "Wednesday 10pm"),
    (datetime(2026, 3, 21, 12, 0), "Saturday 12pm"),
    (datetime(2026, 3, 22, 20, 0), "Sunday 8pm"),
]

print(f"{'Test Case':<30} | {'Is Weekend':<10} | {'In Window':<10}")
print("-" * 55)
for dt, desc in tests:
    is_we, in_win = test_logic(dt)
    print(f"{desc:<30} | {str(is_we):<10} | {str(in_win):<10}")

# Verify current time
now_brt = datetime.now(BRT)
is_we, in_win = test_logic(now_brt)
print(f"\nCurrent BRT ({now_brt.strftime('%Y-%m-%d %H:%M')}): {'Weekend' if is_we else 'Weekday'}, {'In Window' if in_win else 'Out of Window'}")
