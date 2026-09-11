"""
트랙 D — 에이전트 오케스트레이션 (AWS Bedrock 경유 Claude 호출)

실행 전 준비물:
    pip install anthropic boto3
    aws configure 로 AWS 자격증명 설정 완료 (README 참고)
    AWS 콘솔 > Bedrock > Model access 에서 Claude Sonnet 5 활성화 완료
    processed/metadata.csv, processed/features/machine/*.npy,
    processed/variable_names.json (트랙 A/B 산출물)

실행:
    python agent.py 2915          # entity_id 2915번 웨이퍼에 알람이 왔다고 가정

★ 왜 Anthropic API를 직접 안 쓰고 처음부터 Bedrock인가 ★
POC 단계라도 나중에 옮길 걸 알고 있으면 처음부터 그 경로로 가는 게
낫다고 판단함. anthropic 파이썬 SDK의 AnthropicBedrock 클라이언트를
쓰면 .messages.create() 인터페이스가 Anthropic API 직접 호출과 동일해서,
아래 도구 정의·반복 루프·EITL 출력 로직은 API를 직접 썼을 때와 코드가
거의 같다 -- 클라이언트 초기화와 모델 ID 문자열만 다르다.

★ 모델 ID 확인 방법 ★
아래 MODEL 상수가 안 먹히면(ValidationException), 터미널에서
    aws bedrock list-foundation-models --region us-east-1 --by-provider anthropic --query "modelSummaries[*].modelId"
를 실행해서 계정에 실제로 활성화된 정확한 모델 ID로 바꿔 넣을 것.
리전에 따라 "us.anthropic.claude-sonnet-5"처럼 리전 접두사가 붙는
cross-region inference profile ID를 요구하는 경우도 있다.

★ EITL(Expert-In-The-Loop) 설계 ★
이 에이전트는 원인후보와 근거를 "제시"만 하고, 장비를 직접 제어하거나
결론을 확정하지 않는다. 마지막 출력은 항상 "AI 초안 - 검토 필요"로
표시되고, 최종 판단은 사람(공정 엔지니어)이 한다. 코드 상으로도 이
에이전트에는 장비를 제어하는 tool을 아예 주지 않는다 -- 넘겨줄 수
있는 도구가 조회(read-only) 두 개뿐이라 설계적으로 "확정 짓는" 게
불가능하다.
"""
import json
import sys

from anthropic import AnthropicBedrock

from agent_tools import TOOL_SCHEMAS, get_root_cause_ranking, get_fault_reference

BEDROCK_REGION = "us-east-1"  # Claude 모델이 활성화된 리전과 맞출 것
MODEL = "us.anthropic.claude-sonnet-4-6"  # "us." 리전 접두사가 붙은 cross-region
                                           # inference profile ID. 접두사 없는 맨 ID는
                                           # "on-demand throughput isn't supported" 에러가 남
                                           # (실측 확인됨). BEDROCK_REGION이 us-east-1이 아니면
                                           # 그 리전에 맞는 접두사(eu./apac. 등)로 바꿀 것.

SYSTEM_PROMPT = """당신은 반도체 플라즈마 에칭 장비(LAM 9600)의 이상 알람을 \
조사하는 보조 엔지니어입니다.

역할:
1. 알람이 발생한 웨이퍼(entity_id)에 대해 get_root_cause_ranking으로 \
원인후보를 조회합니다.
2. 상위 후보에 대해 get_fault_reference로 배경 지식(역할, 흔한 원인, \
증상)을 조회합니다.
3. 두 정보를 종합해서 공정 엔지니어가 읽을 보고서를 작성합니다.

절대 지켜야 할 것:
- 원인을 "확정"하지 마세요. 항상 "가능성이 높은 후보"로 표현하고, \
최종 판단은 공정 엔지니어의 몫이라고 명시하세요.
- get_fault_reference가 반환하는 내용은 AI가 정리한 일반 지식이지 \
이 장비의 검증된 매뉴얼이 아닙니다. 보고서에 이 사실을 반드시 포함하세요.
- 도구가 찾지 못한 정보(found: false)를 지어내서 채우지 마세요. \
못 찾았으면 못 찾았다고 그대로 보고하세요.
- 보고서는 다음 형식을 따르세요:
  ## 알람 요약
  ## 원인후보 (근거 포함)
  ## 참고 배경지식 (AI 합성 지식, 검증 필요)
  ## 다음 조치 제안 (공정 엔지니어 확인 필요)
"""

TOOL_FUNCTIONS = {
    "get_root_cause_ranking": get_root_cause_ranking,
    "get_fault_reference": get_fault_reference,
}


def call_claude(client: AnthropicBedrock, messages: list):
    return client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=TOOL_SCHEMAS,
        messages=messages,
    )


def run_agent(entity_id: int, max_turns: int = 6) -> dict:
    """보고서 텍스트뿐 아니라, 실제 get_root_cause_ranking 호출 결과(구조화된
    숫자 데이터)도 같이 반환한다. 차트를 그릴 때 LLM이 쓴 마크다운 표를
    다시 파싱하지 않고 이 원본 데이터를 쓰기 위함 -- LLM 출력 형식이
    매번 조금씩 달라져도 차트는 항상 정확하게 그려진다."""
    client = AnthropicBedrock(aws_region=BEDROCK_REGION)  # aws configure로 설정한 자격증명을 자동으로 읽음
    messages = [{
        "role": "user",
        "content": f"entity_id {entity_id}번 웨이퍼에서 이상 알람이 발생했습니다. 조사해서 보고서를 작성해주세요.",
    }]
    captured_ranking = None

    for turn in range(max_turns):
        response = call_claude(client, messages)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            # 더 이상 도구를 안 부르면 최종 보고서로 간주
            final_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return {"report": final_text, "ranking": captured_ranking}

        # tool_use 블록마다 실제 함수를 호출하고 결과를 tool_result로 되돌려줌
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            func = TOOL_FUNCTIONS.get(block.name)
            if func is None:
                result = {"found": False, "reason": f"알 수 없는 도구: {block.name}"}
            else:
                result = func(**block.input)
            if block.name == "get_root_cause_ranking" and result.get("found"):
                captured_ranking = result  # 가장 최근 호출 결과를 차트용으로 보관
            print(f"  [도구 호출] {block.name}({block.input}) -> found={result.get('found')}")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        messages.append({"role": "user", "content": tool_results})

    return {"report": "★ 최대 반복 횟수를 넘겨서 중단했습니다. max_turns를 늘리거나 프롬프트를 점검하세요.",
            "ranking": captured_ranking}


def save_chart(entity_id: int, ranking: dict, out_dir: str) -> str | None:
    """원인후보 top-k의 기여 점수를 막대그래프로 저장. matplotlib이 없으면
    조용히 건너뛴다 (차트는 있으면 좋은 것이지, 없다고 보고서 자체가
    실패하면 안 되므로)."""
    if not ranking or not ranking.get("candidates"):
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (참고) matplotlib이 없어 차트는 건너뜀. 'pip install matplotlib'으로 설치 가능")
        return None

    candidates = ranking["candidates"]
    labels = [f"{c['variable']}\n({c['detail'].split('(')[-1].rstrip(')')})" for c in candidates]
    scores = [c["contribution_score"] for c in candidates]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(range(len(scores)), scores, color="#c0392b")
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9)
    # 축/제목은 영어로 -- matplotlib 기본 폰트(DejaVu Sans)가 한글 글리프를
    # 지원 안 해서 한글로 쓰면 깨진 네모(□)로 나온다. 변수 이름 자체는
    # 원래 영어라 문제없다.
    ax.set_ylabel("PCA Contribution Score (SPE)")
    ax.set_title(f"Root Cause Candidates - entity_id {entity_id}")
    for bar, score in zip(bars, scores):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{score:.1f}",
                 ha="center", va="bottom", fontsize=8)
    fig.tight_layout()

    chart_path = f"{out_dir}/entity_{entity_id}_chart.png"
    fig.savefig(chart_path, dpi=120)
    plt.close(fig)
    return chart_path


def save_report(entity_id: int, result: dict, out_dir: str = "reports") -> str:
    """보고서를 콘솔에만 찍지 않고 .md 파일로 저장한다. GitHub은 .md를
    그대로 렌더링해주기 때문에, 이 파일 하나로 '공정 엔지니어가 읽기
    편한 형태'와 '팀원이 GitHub에서 바로 확인 가능한 형태'가 동시에
    해결된다."""
    import os
    from datetime import datetime

    os.makedirs(out_dir, exist_ok=True)
    chart_path = save_chart(entity_id, result["ranking"], out_dir)

    lines = [
        f"# 알람 조사 보고서 - entity_id {entity_id}",
        "",
        f"- 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 사용 모델: {MODEL} (AWS Bedrock)",
        "",
    ]
    if chart_path:
        lines.append(f"![원인후보 순위 차트]({os.path.basename(chart_path)})")
        lines.append("")
    lines.append(result["report"])

    report_path = f"{out_dir}/entity_{entity_id}_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path


def main():
    if len(sys.argv) < 2:
        print("사용법: python agent.py <entity_id>")
        sys.exit(1)
    entity_id = int(sys.argv[1])

    print(f"entity_id {entity_id} 알람 조사 시작...\n")
    try:
        result = run_agent(entity_id)
    except Exception as e:
        msg = str(e)
        print(f"\n★ 호출 실패: {msg}")
        if "AccessDenied" in msg or "not authorized" in msg:
            print("  -> AWS 콘솔 > Bedrock > Model access에서 Claude Sonnet 5가 "
                  "'Access granted' 상태인지 확인하세요.")
        elif "ValidationException" in msg or "model" in msg.lower():
            print(f"  -> MODEL 상수('{MODEL}')가 계정에서 안 먹히는 ID일 수 있습니다. "
                  "agent.py 상단 docstring의 모델 ID 확인 방법을 참고하세요.")
        elif "credentials" in msg.lower() or "NoCredentialsError" in msg:
            print("  -> aws configure로 자격증명이 설정됐는지 확인하세요.")
        sys.exit(1)

    report_path = save_report(entity_id, result)

    print("\n" + "=" * 60)
    print("★ AI 초안 -- 공정 엔지니어 검토 필요 (자동 확정 아님) ★")
    print("=" * 60)
    print(result["report"])
    print(f"\n보고서 저장됨: {report_path} (GitHub에서 바로 렌더링되는 마크다운)")


if __name__ == "__main__":
    main()
