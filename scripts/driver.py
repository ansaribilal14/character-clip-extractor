"""Budget-limited foreground batch driver for the [HELLO MONSTERS] BEHIND series.

The runtime kills long tool calls (~500s) and background daemons, so this
driver runs ONE budget-limited round per invocation: it keeps executing
resumable pipeline actions (each capped at 360s) until the round budget
expires, then exits cleanly. Re-invoking the same command continues exactly
where it stopped — every stage is sentinel-based and idempotent.

Per episode: download -> pipeline -> full_video.json -> deliver (storage.to
for >50MB, Telegram document below) -> Telegram status -> worklog ->
data-repo push -> disk cleanup.

Credentials come from /home/z/my-project/.secrets/tg.env (NEVER in git) and
are injected into the environment before the delivery module is imported.
"""
import json
import os
import shutil
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACES = os.path.join(REPO, 'workspaces')
STATUS_FILE = os.path.join(WORKSPACES, 'batch_status.json')
WORKLOG = '/home/z/my-project/worklog.md'
SECRETS = '/home/z/my-project/.secrets'
BUDGET_S = 360
STEP_CAP = 300

SERIES = {
    'syt_': 'BABYMONSTER [SEE YOU THERE] TOUR BEHIND',
    'hm_': 'BABYMONSTER [HELLO MONSTERS] BEHIND',
    'nmc_': 'BABYMONSTER CHANNEL NON-MUSIC CONTENT',
}

EPISODES = [
    # SEE YOU THERE tour behind (delivered ones are skipped via batch_status)
    ('syt_01_seoul', 'SDxj3hDFOVI', 'SEOUL'),
    ('syt_02_jakarta', '4NvYGr1YWr4', 'JAKARTA'),
    ('syt_03_bangkok', '-Mu4eVoPmpc', 'BANGKOK'),
    ('syt_04_kobe', 'hPkSSCk0pSY', 'KOBE'),
    ('syt_05_sgtp', 'NNzhI2G8j7c', 'SINGAPORE & TAIPEI'),
    ('syt_06_tokyo', '9G3BYRKujo8', 'TOKYO'),
    ('hm_01_ny3', 'iGjY31tyzUc', 'NY #3'),
    ('hm_02_japan1', 'RX5cXuenZ-Y', 'JAPAN #1'),
    ('hm_03_bonuspage', 'VOhQF_RNnis', 'BONUS PAGE'),
    ('hm_04_la1', 'HFLq5j8wU5Q', 'LA #1'),
    ('hm_05_japan2', 'Whlm77_E3Tg', 'JAPAN #2'),
    ('hm_06_sgp', 'xNF9Sru4IN4', 'SINGAPORE | BM TALKPAWON'),
    ('hm_07_la2', 'EiSPHqAQ28w', 'LA #2'),
    ('hm_08_hkgbkk', 'KCS_4REntgI', 'HONG KONG & BANGKOK | BM TALKPAWON'),
    ('hm_09_ny1', 'JW3t5Vua1-c', 'NY #1'),
    ('hm_10_seoul', 'qoDZQ3-CtCY', 'SEOUL'),
    ('hm_11_nadoc', 'xDx0SiYUw_o', 'NORTH AMERICA DOCUMENTARY'),
    # BABYMONSTER channel non-music contents & non-music
    # behinds (newest-first; music deliverables excluded)
    ('nmc_01_chiquitas_5bite_buldak_c', 'Znkz1nyaaOA', "CHIQUITA’s 5Bite Buldak Challenge 🔥"),
    ('nmc_02_출장_baby_ya_in_kamakura', 'NUcOQHCrVLI', "출장 BABY-YA! in KAMAKURA"),
    ('nmc_03_2026_tima_behind', 'BPLlsHq1Se4', "BABYMONSTER - 2026 TIMA BEHIND"),
    ('nmc_04_summer_sonic_2026_world', 'tO-4QFfSsCo', "BABYMONSTER - SUMMER SONIC 2026 & WORLD TOUR [춤 (CHOOM)] BEHIND in JAPAN #2"),
    ('nmc_05_world_tour_춤_choom_behin', 'UJjvmfRc51c', "BABYMONSTER - WORLD TOUR [춤 (CHOOM)] BEHIND in JAPAN #1"),
    ('nmc_06_moon_music_show_2026_sbs', 'CPyUYQtDgMU', "BABYMONSTER - 'MOON' MUSIC SHOW & 2026 SBS GayoDaejeon Summer BEHIND"),
    ('nmc_07_pharitas_first_solo_prac', 'lhby9P757tU', "PHARITA’s first solo practice vlog 🎤💓"),
    ('nmc_08_moon_m_v_making_film', 'sgsJaUuUN9Y', "BABYMONSTER - 'MOON' M/V MAKING FILM"),
    ('nmc_09_world_tour_춤_choom_behin', 'U_jAcFKeY_c', "BABYMONSTER - WORLD TOUR [춤 (CHOOM)] BEHIND in SEOUL"),
    ('nmc_10_i_like_it_music_show_beh', '8ivjTI42NBM', "BABYMONSTER - 'I LIKE IT' MUSIC SHOW BEHIND"),
    ('nmc_11_i_like_놀이동산_with_ruka_ah', 'DgGJbsttjr4', "I LIKE 놀이동산 with RUKA & AHYEON 🎢🎠"),
    ('nmc_12_i_like_it_m_v_making_fil', 'BddocKDDCfQ', "BABYMONSTER - 'I LIKE IT' M/V MAKING FILM"),
    ('nmc_13_sugar_honey_ice_tea_musi', 'GsU1GTVON6o', "BABYMONSTER - 'SUGAR HONEY ICE TEA' MUSIC SHOW BEHIND"),
    ('nmc_14_ahyeons_voice_memo', 'Zj0hpfQw9kc', "AHYEON's voice memo"),
    ('nmc_15_backstage_with_asa', 'O1vQBTJbkqE', "backstage with ASA 🍬🍯🧊🫖"),
    ('nmc_16_2026_27_babymonster_worl', 'vTdnuR1g4kU', "2026-27 BABYMONSTER WORLD TOUR [춤 (CHOOM)] CONCEPT FILM"),
    ('nmc_17_sugar_honey_ice_tea_reco', 'nrAeweP4TqU', "BABYMONSTER - 'SUGAR HONEY ICE TEA' RECORDING BEHIND"),
    ('nmc_18_into_chiquitas_world', 'tCD3K7uiF7k', "Into CHIQUITA's World 🧜‍♀️"),
    ('nmc_19_sugar_honey_ice_tea_m_v', 'hMiGDgQhER8', "BABYMONSTER - 'SUGAR HONEY ICE TEA' M/V MAKING FILM"),
    ('nmc_20_babymonster_sugar_honey', 'xN3X_tl4zlQ', "BABYMONSTER ‘SUGAR HONEY ICE TEA’ 응원법🍬🍯🧊🍵"),
    ('nmc_21_춤_choom_music_show_behin', 'OiIWhgIWw9Q', "BABYMONSTER - '춤 (CHOOM)' MUSIC SHOW BEHIND"),
    ('nmc_22_welcome_to_our_monster_p', 'M7svI2HiMno', "BABYMONSTER - WELCOME TO OUR MONSTER PARTY"),
    ('nmc_23_춤_choom_recording_behind', 'yOO8cebU-Qk', "BABYMONSTER - '춤 (CHOOM)' RECORDING BEHIND"),
    ('nmc_24_춤_choom_performance_vide', '9buM0AdOvSM', "BABYMONSTER - '춤 (CHOOM)' PERFORMANCE VIDEO BEHIND"),
    ('nmc_25_babymonster_춤_choom_응원법', '9DlDGxKQsDg', "BABYMONSTER ‘춤 (CHOOM)’ 응원법😈"),
    ('nmc_26_춤_choom_m_v_making_film', 'V5RA_mcGHGM', "BABYMONSTER - '춤 (CHOOM)' M/V MAKING FILM"),
    ('nmc_27_2026_27_babymonster_worl', 'WY9mRnEFapE', "2026-27 BABYMONSTER WORLD TOUR [춤 (CHOOM)] SPOT VIDEO"),
    ('nmc_28_baemon_news_7_the_1st_bm', 'NjEGmMsX04E', "[BAEMON NEWS 7] THE 1ST BM AWARDS... AND MORE BEHIND THE SCENES"),
    ('nmc_29_baemon_news_7_the_1st_bm', 'UwLCZnFLOYU', "[BAEMON NEWS 7] THE 1ST BM AWARDS… AND MORE"),
    ('nmc_30_2026_27_babymonster_worl', 'KDqrlqqbEF4', "2026-27 BABYMONSTER WORLD TOUR TEASER VIDEO"),
    ('nmc_31_really_like_you_music_sh', 'CAdRNXmkuc4', "BABYMONSTER - ‘Really Like You’ MUSIC SHOW BEHIND"),
    ('nmc_32_2025_sbs_gayodaejeon_beh', 'P6jk7mlOl7w', "BABYMONSTER - 2025 SBS GayoDaejeon BEHIND"),
    ('nmc_33_supa_dupa_luv_m_v_making', 'K29r_Y_6K7M', "BABYMONSTER - ‘SUPA DUPA LUV' M/V MAKING FILM"),
    ('nmc_34_2025_mama_awards_behind', '-kB9Zj47kd8', "BABYMONSTER - 2025 MAMA AWARDS BEHIND"),
    ('nmc_35_psycho_performance_video', 'vxXAbY1ouXU', "BABYMONSTER - ‘PSYCHO’ PERFORMANCE VIDEO BEHIND"),
    ('nmc_36_psycho_m_v_making_film', 'E0_WTbwjcYM', "BABYMONSTER - ‘PSYCHO’ M/V MAKING FILM"),
    ('nmc_37_we_go_up_jacket_behind', 'PsxAtYyMc2o', "BABYMONSTER - [WE GO UP] JACKET BEHIND"),
    ('nmc_38_we_go_up_music_show_behi', 'DNFLk1bKios', "BABYMONSTER - 'WE GO UP' MUSIC SHOW BEHIND"),
    ('nmc_39_baemon_house_ep8', 'Lsy68wAQdWQ', "BAEMON HOUSE EP.8"),
    ('nmc_40_we_go_up_exclusive_perfo', 'kIBeFphuZK0', "BABYMONSTER - ‘WE GO UP’ EXCLUSIVE PERFORMANCE VIDEO BEHIND"),
    ('nmc_41_baemon_house_ep7', 'c5aBG9Warls', "BAEMON HOUSE EP.7"),
    ('nmc_42_we_go_up_recording_behin', 'uyxvtl-euzs', "BABYMONSTER - ‘WE GO UP’ RECORDING BEHIND"),
    ('nmc_43_baemon_house_ep6', '6Ej3fKYC39g', "BAEMON HOUSE EP.6"),
    ('nmc_44_babymonster_we_go_up_응원법', 'x4b_9YdhT8M', "BABYMONSTER ‘WE GO UP’ 응원법🆙"),
    ('nmc_45_we_go_up_m_v_making_film', 'WwCU6xujDcY', "BABYMONSTER - ‘WE GO UP’ M/V MAKING FILM"),
    ('nmc_46_baemon_house_ep5', 'YLuxilQonrM', "BAEMON HOUSE EP.5"),
    ('nmc_47_baemon_house_ep4', '_vQIO3IyC-0', "BAEMON HOUSE EP.4"),
    ('nmc_48_baemon_house_ep3', 'd77EB6_6ock', "BAEMON HOUSE EP.3"),
    ('nmc_49_baemon_house_ep2', '5b-CmKweNGE', "BAEMON HOUSE EP.2"),
    ('nmc_50_baemon_house_ep1', 'o48-eZGkHgk', "BAEMON HOUSE EP.1"),
    ('nmc_51_baemon_house_ep0', '9O7GZKZBak8', "BAEMON HOUSE EP.0"),
    ('nmc_52_2025_sbs_gayodaejeon_sum', 'njeIzKIxWYQ', "BABYMONSTER - 2025 SBS GayoDaejeon Summer BEHIND"),
    ('nmc_53_hot_sauce_music_show_beh', 'GttvatKV014', "BABYMONSTER - 'HOT SAUCE' MUSIC SHOW BEHIND"),
    ('nmc_54_hot_sauce_m_v_making_fil', 'cwlh2mo45tg', "BABYMONSTER - ‘HOT SAUCE’ M/V MAKING FILM"),
    ('nmc_55_2025_babymonster_1st_wor', 'zhpnLvs9Afw', "2025 BABYMONSTER 1st WORLD TOUR [HELLO MONSTERS] IN NORTH AMERICA - MESSAGE VIDEO"),
    ('nmc_56_hot_sauce_recording_behi', '5B9DNHihmg4', "BABYMONSTER - ‘HOT SAUCE’ RECORDING BEHIND"),
    ('nmc_57_babymonster_hot_sauce_응원', 'wBHKLsujSNA', "BABYMONSTER ‘HOT SAUCE’ 응원법🔥"),
    ('nmc_58_hello_monsters_behind_in', 'FudJ4cvO--A', "BABYMONSTER - [HELLO MONSTERS] BEHIND in NY #2 | WORLD TOUR DIARY"),
    ('nmc_59_2025_babymonster_1st_wor', 'AiwfNZ_wC_Q', "2025 BABYMONSTER 1st WORLD TOUR [HELLO MONSTERS] SPOT VIDEO #2"),
    ('nmc_60_billionaire_exclusive_pe', 'zEsAESce-ao', "BABYMONSTER - 'BILLIONAIRE' EXCLUSIVE PERFORMANCE VIDEO BEHIND"),
    ('nmc_61_2024_sbs_gayodaejeon_beh', 'gqCi4vuObsA', "BABYMONSTER - 2024 SBS GayoDaejeon BEHIND"),
    ('nmc_62_really_like_you_m_v_maki', 'wnv0KSPI_kU', "BABYMONSTER - 'Really Like You' M/V MAKING FILM"),
    ('nmc_63_clik_clak_m_v_making_fil', '-gz70mUm73s', "BABYMONSTER - 'CLIK CLAK' M/V MAKING FILM"),
    ('nmc_64_drip_clik_clak_1st_music', '4mRw7AFO89g', "BABYMONSTER - 'DRIP & CLIK CLAK' 1st MUSIC SHOW BEHIND"),
    ('nmc_65_drip_recording_behind', '4sPvEP-nE4E', "BABYMONSTER - 'DRIP' RECORDING BEHIND"),
    ('nmc_66_2025_new_year_greeting', 'pue-fNCt_Xs', "BABYMONSTER - 2025 New Year Greeting"),
    ('nmc_67_2025_babymonster_1st_wor', 'O1pJNaXwrqw', "2025 BABYMONSTER 1st WORLD TOUR [HELLO MONSTERS] SPOT VIDEO"),
    ('nmc_68_love_in_my_heart_m_v_mak', 'WBMQuE8vnAQ', "BABYMONSTER - 'Love In My Heart' M/V MAKING FILM"),
    ('nmc_69_drip_clik_clak_performan', 'aNHMgxZCAto', "BABYMONSTER - 'DRIP & CLIK CLAK' PERFORMANCE VIDEO BEHIND"),
    ('nmc_70_drip_clik_clak_special_p', 'B7F1yKD_-TY', "BABYMONSTER - 'DRIP & CLIK CLAK' SPECIAL PERFORMANCE VIDEO BEHIND"),
    ('nmc_71_2025_babymonster_1st_wor', 'QclXARMU8Wc', "2025 BABYMONSTER 1st WORLD TOUR [HELLO MONSTERS] IN SEOUL SPOT VIDEO"),
    ('nmc_72_baemon_news_7_new_album', 'ltVP3e8R9Cw', "[BAEMON NEWS 7] NEW ALBUM COMING IN BEHIND THE SCENES"),
    ('nmc_73_drip_m_v_making_film', 'JkGHAcrbnF0', "BABYMONSTER - ‘DRIP’ M/V MAKING FILM"),
    ('nmc_74_clik_clak_m_v_reaction', 'oEPolymOfv4', "BABYMONSTER - ‘CLIK CLAK' M/V REACTION"),
    ('nmc_75_babymonster_drip_응원법_pro', 'X2GfGkH-3hg', "BABYMONSTER 'DRIP' 응원법 (Produced by. 😈)"),
    ('nmc_76_baemon_news_7_new_album', 'wtVeAPimOyo', "[BAEMON NEWS 7] NEW ALBUM COMING IN"),
    ('nmc_77_2024_tmea_music_festival', '48Fys9K3s8Y', "BABYMONSTER - 2024 TMEA Music Festival BEHIND"),
    ('nmc_78_forever_music_show_behin', 'Bfe4U7053U8', "BABYMONSTER - ‘FOREVER’ MUSIC SHOW BEHIND"),
    ('nmc_79_baemon_news_7_babymonste', 't72lwP600ew', "[BAEMON NEWS 7] BABYMONSTER FANDOM NAME RELEASE (NG CUTS ver.)"),
    ('nmc_80_baemon_news_7_babymonste', 'zFhT2bMzgEc', "[BAEMON NEWS 7] BABYMONSTER FANDOM NAME RELEASE"),
    ('nmc_81_forever_dance_performanc', '8Gey-Zw1DJw', "BABYMONSTER - ‘FOREVER’ DANCE PERFORMANCE VIDEO BEHIND"),
    ('nmc_82_forever_m_v_making_film', 'tGHRkWUXrPg', "BABYMONSTER - ‘FOREVER’ M/V MAKING FILM"),
    ('nmc_83_like_that_performance_vi', 'ET6LN7N-wRk', "BABYMONSTER - ‘LIKE THAT’ PERFORMANCE VIDEO BEHIND"),
    ('nmc_84_babymonster_presents_see', 'g6Gerc1yOSk', "BABYMONSTER PRESENTS : SEE YOU THERE SPOT VIDEO"),
    ('nmc_85_sheesh_the_last_music_sh', 'WFkulBriLnY', "BABYMONSTER - 'SHEESH' The LAST MUSIC SHOW BEHIND"),
    ('nmc_86_sheesh_1st_music_show_be', 'TEesENVFlrE', "BABYMONSTER - 'SHEESH' 1st MUSIC SHOW BEHIND"),
    ('nmc_87_babymons7er_offline_fan', 'ZKHFnRfb8no', "BABYMONSTER - [BABYMONS7ER] OFFLINE FAN SIGNING EVENT BEHIND"),
    ('nmc_88_g_park_radio_show_behind', 'wlOoOT2zSRQ', "BABYMONSTER - G-Park Radio Show BEHIND"),
    ('nmc_89_1st_mini_album_babymons7', 'C-h4yERrS7Y', "BABYMONSTER - 1st MINI ALBUM [BABYMONS7ER] POP-UP STORE BEHIND"),
    ('nmc_90_sheesh_performance_video', 'RLqKlb1v-Mo', "BABYMONSTER - 'SHEESH' PERFORMANCE VIDEO BEHIND"),
    ('nmc_91_sheesh_m_v_making_film', 'offkoMoFh5U', "BABYMONSTER - ‘SHEESH’ M/V MAKING FILM"),
    ('nmc_92_sheesh_m_v_reaction', 'WeDemXei4sc', "BABYMONSTER - 'SHEESH' M/V REACTION"),
    ('nmc_93_babymons7er_visual_film', '1myrYL8ybzM', "[BABYMONS7ER] VISUAL FILM"),
    ('nmc_94_baemon_tv_haunted_house', '7YxRHgEfVEE', "BAEMON TV - HAUNTED HOUSE EP.02"),
    ('nmc_95_baemon_tv_haunted_house', 'uQ9rQ5PYH0U', "BAEMON TV - HAUNTED HOUSE EP.01"),
    ('nmc_96_stuck_in_the_middle_spec', 'DnCrSJZF9jY', "BABYMONSTER - ‘Stuck In The Middle’ SPECIAL STAGE BEHIND"),
    ('nmc_97_stuck_in_the_middle_m_v', 'i1knixNt1TM', "BABYMONSTER - ‘Stuck In The Middle’ M/V REACTION"),
    ('nmc_98_stuck_in_the_middle_m_v', 'U5UUEEEf0cI', "BABYMONSTER - ‘Stuck In The Middle’ M/V MAKING FILM EP.2"),
    ('nmc_99_babymonster_next_phase_y', '3piGcUtxBD0', "BABYMONSTER NEXT PHASE | YG Announcement"),
    ('nmc_100_batter_up_live_performan', 'ly6vEAWNing', "BABYMONSTER - 'BATTER UP' LIVE PERFORMANCE (Stadium Ver.) BEHIND"),
    ('nmc_101_batter_up_live_performan', 'KFDs6yS1WPY', "BABYMONSTER - 'BATTER UP' LIVE PERFORMANCE (School Ver.) BEHIND"),
    ('nmc_102_batter_up_dance_performa', 'oFs8WS6ZifM', "BABYMONSTER - 'BATTER UP' DANCE PERFORMANCE BEHIND"),
    ('nmc_103_batter_up_m_v_reaction', 'vWv1l1R-hwg', "BABYMONSTER - 'BATTER UP' M/V REACTION"),
    ('nmc_104_a_thank_you_message', 'hDWoGExKWCs', "BABYMONSTER - A THANK YOU MESSAGE"),
    ('nmc_105_batter_up_m_v_making_fil', '39QFE09ozj0', "BABYMONSTER - ‘BATTER UP’ M/V MAKING FILM EP.3"),
    ('nmc_106_batter_up_m_v_making_fil', 'nAr1v7cnqlE', "BABYMONSTER - ‘BATTER UP’ M/V MAKING FILM EP.2"),
    ('nmc_107_batter_up_m_v_making_fil', 'z01D9rfRzvA', "BABYMONSTER - ‘BATTER UP’ M/V MAKING FILM EP.1"),
    ('nmc_108_debut_member_announcemen', 'Un6bwJ3W8H8', "BABYMONSTER - DEBUT MEMBER ANNOUNCEMENT REACTION"),
    ('nmc_109_debut_member_announcemen', 'A-IfMVE885A', "BABYMONSTER - DEBUT MEMBER ANNOUNCEMENT VIDEO"),
    ('nmc_110_last_evaluation_ep8', 'Gi0ezbc0OwU', "BABYMONSTER - 'Last Evaluation' EP.8"),
    ('nmc_111_last_evaluation_ep7', 'k2GNcev8kaA', "BABYMONSTER - 'Last Evaluation' EP.7"),
    ('nmc_112_last_evaluation_ep6', 'W8qUoHsE-wQ', "BABYMONSTER - 'Last Evaluation' EP.6"),
    ('nmc_113_last_evaluation_behind_t', 'Am2NBfQ3I2g', "BABYMONSTER - 'Last Evaluation' Behind The Scenes #4"),
    ('nmc_114_last_evaluation_ep5', 'geVfm6A7CHw', "BABYMONSTER - 'Last Evaluation' EP.5"),
    ('nmc_115_last_evaluation_behind_t', 'YGG3936Bt2c', "BABYMONSTER - 'Last Evaluation' Behind The Scenes #3"),
    ('nmc_116_last_evaluation_ep4', 'LN-G05mqGjY', "BABYMONSTER - 'Last Evaluation' EP.4"),
    ('nmc_117_last_evaluation_teaser_2', 'DPbKTXnVC9U', "BABYMONSTER - 'Last Evaluation' TEASER #2"),
    ('nmc_118_last_evaluation_ep3', 'mO9VkglQKgg', "BABYMONSTER - 'Last Evaluation' EP.3"),
    ('nmc_119_last_evaluation_behind_t', 'Kxb0aUqmex0', "BABYMONSTER - 'Last Evaluation' Behind The Scenes #2"),
    ('nmc_120_last_evaluation_ep2', '4pcmRcjMhvc', "BABYMONSTER - 'Last Evaluation' EP.2"),
    ('nmc_121_last_evaluation_behind_t', 'MVHO7NXFSAc', "BABYMONSTER - 'Last Evaluation' Behind The Scenes #1"),
    ('nmc_122_last_evaluation_ep1', 'hCgZqFscMp0', "BABYMONSTER - 'Last Evaluation' EP.1"),
    ('nmc_123_last_evaluation_teaser', 'l4i0XmCVbn0', "BABYMONSTER - 'Last Evaluation' TEASER"),
    ('nmc_124_haram_character_playlist', '1b1d02JT1rQ', "BABYMONSTER - HARAMㅣCharacter Playlist"),
    ('nmc_125_introducing_haram', 'qpisgDPf2Q4', "BABYMONSTER - Introducing HARAM"),
    ('nmc_126_ahyeon_character_playlis', 'ke4u__QBHAo', "BABYMONSTER - AHYEONㅣCharacter Playlist"),
    ('nmc_127_introducing_ahyeon', '8i_wZQoqbwU', "BABYMONSTER - Introducing AHYEON"),
    ('nmc_128_chiquita_character_playl', 'pjBI1aHXSfA', "BABYMONSTER - CHIQUITAㅣCharacter Playlist"),
    ('nmc_129_introducing_chiquita', 'i9Eiij6Wb94', "BABYMONSTER - Introducing CHIQUITA"),
    ('nmc_130_asa_character_playlist', 'WbtrLUNEc-U', "BABYMONSTER - ASAㅣCharacter Playlist"),
    ('nmc_131_introducing_asa', 'x6FlVjfVqmg', "BABYMONSTER - Introducing ASA"),
    ('nmc_132_rora_character_playlist', 'aC8HlzSurf0', "BABYMONSTER - RORAㅣCharacter Playlist"),
    ('nmc_133_introducing_rora', 'nVqUHk3GSbY', "BABYMONSTER - Introducing RORA"),
    ('nmc_134_pharita_character_playli', 'Mr2qYqFQn3Q', "BABYMONSTER - PHARITAㅣCharacter Playlist"),
    ('nmc_135_introducing_pharita', 'z7B0WHMCvZM', "BABYMONSTER - Introducing PHARITA"),
    ('nmc_136_ruka_character_playlist', '6DiI3f8GWv4', "BABYMONSTER - RUKAㅣCharacter Playlist"),
    ('nmc_137_introducing_ruka', 'asYFbkO450I', "BABYMONSTER - Introducing RUKA"),

]


def _pick_cli_python():
    """Pick an interpreter that can actually import the full stack.
    The platform venv and /usr/bin/python3 may differ in site-packages."""
    cands = [os.environ.get('CCE_PY'), '/usr/bin/python3', sys.executable]
    check = ('import character_clip_extractor, insightface, cv2, requests')
    for c in cands:
        if not c:
            continue
        try:
            r = subprocess.run([c, '-c', check], capture_output=True, timeout=90)
            if r.returncode == 0:
                return c
        except Exception:
            continue
    return sys.executable


CLI_PY = _pick_cli_python()


def log(m):
    print(f'[driver] {m}', flush=True)


def load_secrets():
    """Load every .env file in the secrets dir (tg.env, gh.env, ...)."""
    vals = {}
    try:
        for fn in sorted(os.listdir(SECRETS)):
            if not fn.endswith('.env'):
                continue
            for line in open(os.path.join(SECRETS, fn)):
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    k = k.strip()
                    if k in ('TG_TOKEN', 'TG_CHAT'):
                        k = 'CCE_' + k
                    vals[k] = v.strip()
    except OSError:
        pass
    return vals


def _preload_env():
    """Inject env-only secrets BEFORE importing the delivery module (it
    reads CCE_TG_TOKEN / CCE_TG_CHAT / CCE_VISITOR_TOKEN_FILE at import)."""
    for k, v in load_secrets().items():
        os.environ.setdefault(k, v)
    os.environ.setdefault('CCE_VISITOR_TOKEN_FILE',
                          os.path.join(WORKSPACES, 'storage_visitor_token.txt'))


_preload_env()
sys.path.insert(0, REPO)
from character_clip_extractor import refs, delivery, downloader  # noqa: E402


def base_of(name):
    return os.path.join(WORKSPACES, name)


def full_video_json(base):
    p = os.path.join(base, 'output', 'analysis', 'full_video.json')
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            return None
    return None


def is_zero_scene_episode(base):
    """True when analysis ran to completion and found zero target scenes
    (e.g. solo-member content): export plan exists with no windows."""
    an = os.path.join(base, 'output', 'analysis')
    ep = os.path.join(an, 'export_plan.json')
    gp = os.path.join(an, 'grouped_scenes.json')
    if not (os.path.exists(ep) and os.path.exists(gp)
            and os.path.exists(os.path.join(an, 'qc.json'))):
        return False
    try:
        plan = json.load(open(ep))
        return len(plan.get('clips') or []) == 0
    except Exception:
        return False


def finish_zero_episode(name, vid, title, s, reason):
    """Complete an episode that honestly contains no target scenes."""
    base = base_of(name)
    ep = s['episodes'].setdefault(name, {})
    ep.update({'title': title, 'delivered': True, 'kind': 'none',
               'url': '', 'size_mb': 0, 'delivered_at':
                   time.strftime('%Y-%m-%d %H:%M'), 'note': reason})
    save_status(s)
    series = next((v for k, v in SERIES.items() if name.startswith(k)),
                  'BABYMONSTER')
    try:
        delivery._tg('sendMessage', {
            'chat_id': delivery.TG_CHAT,
            'text': (f'ℹ️ {series} — {title}\n'
                     f'No Ahyeon scenes detected in this video — nothing to '
                     f'deliver.\nhttps://youtu.be/{vid}'),
            'disable_web_page_preview': True})
    except Exception:
        pass
    worklog_append(name, f'{series} — {title}', [
        f'zero-scene episode: {reason}',
        'raw visibility 0s / no grouped windows — honest negative result',
        'nothing uploaded; state marked complete; disk reclaimed',
    ])
    for p in (os.path.join(base, 'output', 'source'),
              os.path.join(base, 'output', 'analysis', 'normalized.mp4'),
              os.path.join(base, 'output', 'clips')):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
    push_data(f'batch data: {name} ({title}) DONE (zero target scenes)')
    return True


def full_video_path(base):
    fj = full_video_json(base)
    if fj and fj.get('full_video'):
        p = os.path.join(base, 'output', 'clips', 'ahyeon', fj['full_video'])
        if os.path.exists(p):
            return p
    return None


def save_status(s):
    os.makedirs(WORKSPACES, exist_ok=True)
    # ensure_ascii=True: astral chars escape as \\uXXXX pairs (safe), and any
    # stray lone surrogate also escapes instead of crashing the UTF-8 encode.
    json.dump(s, open(STATUS_FILE, 'w'), indent=1, ensure_ascii=True)


def push_data(msg):
    try:
        subprocess.run(['git', 'add', '-A'], cwd=WORKSPACES, check=True, timeout=180)
        subprocess.run(['git', '-c', 'user.name=bot', '-c', 'user.email=bot@ansaribilal14.dev',
                        'commit', '-q', '-m', msg], cwd=WORKSPACES, check=True, timeout=180)
        subprocess.run(['git', 'push', '-q', 'data', 'HEAD:main', '--force'],
                       cwd=WORKSPACES, check=True, timeout=300)
        log(f'data repo pushed: {msg}')
    except Exception as e:
        log(f'data push failed: {e}')


def worklog_append(name, title, lines):
    stamp = time.strftime('%Y-%m-%d %H:%M')
    try:
        with open(WORKLOG, 'a') as f:
            f.write(f'\n---\nTask ID: hm-batch/{name}\nAgent: driver\nTask: '
                    f'{title} — process & deliver\n\nWork Log:\n')
            for ln in lines:
                f.write(f'- {ln}\n')
            f.write(f'\nStage Summary:\n- {title} completed and delivered ({stamp})\n')
    except OSError as e:
        log(f'worklog append failed: {e}')


def deliver_episode(name, vid, title, s):
    base = base_of(name)
    fvp = full_video_path(base)
    fj = full_video_json(base)
    if not fvp or not fj:
        log(f'{name}: full_video.json present but file missing — rerun 10_concat_full')
        return False
    size_mb = fj.get('size_mb') or os.path.getsize(fvp) / 1e6
    series = next((v for k, v in SERIES.items() if name.startswith(k)),
                  'BABYMONSTER')
    cap = (f'{series} — {title}\n'
           f'Ahyeon full-video cut · {fj.get("n_windows", "?")} windows · '
           f'{fj.get("duration_s", 0):.0f}s · {fj.get("resolution", "?")} · CRF16\n'
           f'https://youtu.be/{vid}')
    log(f'delivering {name} ({size_mb:.1f} MB) ...')
    res = delivery.deliver_auto(fvp, cap, keep=False)
    url = res.get('url') or ''
    # storage.to upload+confirm is the source of truth; a TG hiccup must not
    # trigger a duplicate re-upload. Fallback-notify below instead.
    ok = bool(res.get('ok')) or bool(url and res.get('filename'))
    log(f'delivery: kind={res.get("kind")} ok={ok} url={url}')
    if url and not res.get('ok'):
        try:
            delivery._tg('sendMessage', {
                'chat_id': delivery.TG_CHAT,
                'text': (f"📁 <b>{res.get('filename')}</b>\n"
                         f"💾 Size: {res.get('human_size', '?')}\n"
                         f"⏳ Available until: {res.get('expires_at', 'n/a')}\n"
                         f"⬇️ Download: {url}"),
                'disable_web_page_preview': False})
        except Exception:
            pass
    if not ok:
        ep = s['episodes'].setdefault(name, {})
        ep['deliver_fail'] = int(ep.get('deliver_fail', 0)) + 1
        save_status(s)
        log(f'{name}: delivery NOT confirmed (attempt '
            f'{ep["deliver_fail"]}) — will retry next round')
        return False
    ep = s['episodes'].setdefault(name, {})
    ep.update({'title': title, 'delivered': True, 'kind': res.get('kind'),
               'url': url, 'expires_at': res.get('expires_at'),
               'size_mb': round(size_mb, 2),
               'delivered_at': time.strftime('%Y-%m-%d %H:%M')})
    save_status(s)
    try:
        json.dump(res, open(os.path.join(base, 'output', 'analysis',
                                         'delivery.json'), 'w'), indent=1)
    except OSError:
        pass
    worklog_append(name, f'{series} — {title}', [
        f'delivered via {res.get("kind")}: {url or "(no url returned)"}',
        f'{fj.get("n_windows")} windows, {fj.get("duration_s", 0):.0f}s, '
        f'{fj.get("resolution")}, {size_mb:.1f} MB',
        'source + normalized + clips deleted after confirm (disk reclaimed)',
    ])
    for p in (os.path.join(base, 'output', 'source'),
              os.path.join(base, 'output', 'analysis', 'normalized.mp4'),
              os.path.join(base, 'output', 'clips')):
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            log(f'cleaned dir {p}')
        elif os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    push_data(f'batch data: {name} ({title}) DONE + delivered')
    return True


def run_cli(name, vid, left):
    base = base_of(name)
    os.makedirs(base, exist_ok=True)
    ok, msg = refs.ensure_references(base, 'ahyeon', None, False)
    log(f'references: {msg}')
    if not ok:
        raise RuntimeError('reference setup failed')
    # farm artifact pickup BEFORE the pipeline: a completed farm run for this
    # video means we can skip direct-download attempts entirely
    src_dir = os.path.join(base, 'output', 'source')
    os.makedirs(src_dir, exist_ok=True)
    have_src = bool(downloader._pick_verified(src_dir)) \
        if os.path.isdir(src_dir) else False
    have_norm = os.path.exists(
        os.path.join(base, 'output', 'analysis', 'normalized.mp4'))
    if not have_src and not have_norm:
        t = time.monotonic()
        try:
            got = downloader._farm_pickup(f'https://youtu.be/{vid}', src_dir)
            if got:
                log(f'farm pickup: {got} ({time.monotonic() - t:.0f}s)')
        except Exception as e:
            log(f'farm pickup error (continuing): {e}')
        used = time.monotonic() - t
        if not have_src and not have_norm and left - used < 90:
            log('round budget consumed by pickup; CLI deferred to next round')
            return 0
    env = dict(os.environ)
    env.update(load_secrets())
    env['CCE_VISITOR_TOKEN_FILE'] = os.path.join(
        WORKSPACES, 'storage_visitor_token.txt')
    cmd = [CLI_PY, '-m', 'character_clip_extractor',
           '--url', f'https://youtu.be/{vid}', '--character', 'ahyeon',
           '--out', base, '--pad', '5', '--max-height', '1080',
           '--no-zip', '--no-deliver']
    timeout = max(5, min(STEP_CAP, int(left)))
    log(f'>>> CLI round (timeout {timeout}s): {name} [py={CLI_PY}]')
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, errbuf = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        # kill the whole process group: orphaned ffmpeg children would keep
        # the stdout pipe open and hang communicate() until the tool kill
        import signal
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            proc.kill()
        log('CLI round hit budget (process group killed; resumes next round)')
        try:
            proc.communicate(timeout=30)
        except Exception:
            pass
        return 0
    tail = '\n'.join((out or '').strip().splitlines()[-12:])
    if tail:
        print(tail, flush=True)
    if rc != 0:
        err = ' | '.join((errbuf or '').strip().splitlines()[-4:])
        log(f'CLI rc={rc}: {err}')
        return rc
    return 0


def status_table(s):
    print(f'{"episode":16} {"title":34} {"state":16} url')
    for name, vid, title in EPISODES:
        ep = s['episodes'].get(name, {})
        base = base_of(name)
        state = ('delivered' if ep.get('delivered')
                 else 'ready-to-deliver' if full_video_json(base)
                 else 'pending')
        print(f'{name:16} {title[:34]:34} {state:16} {ep.get("url") or "-"}')


def main():
    t0 = time.time()
    os.makedirs(WORKSPACES, exist_ok=True)
    s = json.load(open(STATUS_FILE)) if os.path.exists(STATUS_FILE) \
        else {'episodes': {}}
    for name, vid, title in EPISODES:
        s['episodes'].setdefault(name, {'title': title, 'delivered': False})
    if '--status' in sys.argv:
        status_table(s)
        return 0
    for name, vid, title in EPISODES:
        ep = s['episodes'].get(name, {})
        if ep.get('delivered'):
            continue
        base = base_of(name)
        left = BUDGET_S - (time.time() - t0)
        if left < 90:
            log('round budget exhausted; clean exit (re-run to continue)')
            return 0
        if full_video_json(base):
            if left < 300:
                log(f'{name}: full video ready, delivery deferred '
                    f'(need ~300s, have {left:.0f}s)')
                return 0
            deliver_episode(name, vid, title, s)
        else:
            fails = int(ep.get('fail_count', 0))
            if fails >= 4:
                log(f'{name}: {fails} consecutive failures — blocked, skipping '
                    f'to next episode this round')
                continue
            rc = run_cli(name, vid, left)
            if rc != 0:
                # a completed analysis with zero target scenes exits non-zero
                # at 10_concat (assert: no exportable windows) — finish it
                # honestly instead of retrying forever
                if is_zero_scene_episode(base):
                    finish_zero_episode(
                        name, vid, title, s,
                        'export plan has 0 windows (target not detected)')
                    continue
                ep['fail_count'] = fails + 1
                save_status(s)
                log(f'{name}: failed ({fails + 1}/4) — ending round, retry next round')
                return 0                      # dedicated retry next round
            if 'fail_count' in ep:
                ep.pop('fail_count')
                save_status(s)
            if full_video_json(base):
                left = BUDGET_S - (time.time() - t0)
                if left >= 300:
                    deliver_episode(name, vid, title, s)
                else:
                    log(f'{name}: full video ready; delivery next round')
            elif is_zero_scene_episode(base):
                finish_zero_episode(
                    name, vid, title, s,
                    'export plan has 0 windows (target not detected)')
        if time.time() - t0 >= BUDGET_S:
            log('round budget exhausted; clean exit (re-run to continue)')
            return 0
    log('ALL EPISODES PROCESSED')
    return 0


if __name__ == '__main__':
    rc = main()
    # Skip interpreter teardown: onnxruntime/insightface teardown can hang
    # for minutes after killed CLI children, blowing the tool-call budget.
    # All state files are already flushed (refcount-closed / with-blocks).
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
