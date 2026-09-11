"""
GitHub에 올리기 전, 데모용 보고서를 여러 건 한 번에 뽑는 스크립트.

★ 고른 entity_id 기준 ★
정답이 이미 알려진(fault_label 존재) 웨이퍼 중, label_reliable=True인
것들 위주로 골랐다. 계열(RF/Cl2/TCP)별로 성능이 다르다는 걸 이미 알고
있으므로, "잘 맞는 사례"와 "애매한 사례"를 섞어서 정직한 데모 세트가
되도록 함. label_reliable=False였던 5건(2918/2937/3141/3142/3339)은
라벨 자체가 못 미더운 케이스라 데모에서 제외.

실행:
    python run_demo_batch.py
    python run_demo_batch.py 2916 2917 3121   # 특정 entity_id만 지정도 가능
"""
import sys

from agent import run_agent, save_report

# RF(정확도 높았던 계열) 2개, Cl2 1개, TCP 1개(부분 성공 사례), He 1개(단일 사례)
DEFAULT_ENTITY_IDS = [2916, 2917, 2939, 2915, 2931]


def main():
    entity_ids = [int(x) for x in sys.argv[1:]] or DEFAULT_ENTITY_IDS
    print(f"{len(entity_ids)}건 실행 예정: {entity_ids}\n")

    succeeded, failed = [], []
    for eid in entity_ids:
        print(f"{'='*50}\nentity_id {eid} 조사 중...\n{'='*50}")
        try:
            result = run_agent(eid)
            path = save_report(eid, result)
            print(f"  -> 완료: {path}\n")
            succeeded.append(eid)
        except Exception as e:
            print(f"  -> 실패: {e}\n")
            failed.append(eid)

    print(f"\n총 {len(entity_ids)}건 중 성공 {len(succeeded)}건, 실패 {len(failed)}건")
    if succeeded:
        print(f"성공: {succeeded}")
    if failed:
        print(f"실패 (재시도 필요): {failed}")
    print("\nreports/ 폴더를 열어서 .md 파일들을 하나씩 확인하세요.")


if __name__ == "__main__":
    main()
