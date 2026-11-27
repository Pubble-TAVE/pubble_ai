"""현황판 5칸 계산 테스트. 모델도 API도 쓰지 않는다."""

import pytest
from pydantic import ValidationError

from app.config import BoardSettings
from app.schemas.board import BoardRequest, BoardResponse
from app.services.board import (
    Cluster,
    ClusterPoint,
    ExcludedReaction,
    Point,
    Reaction,
    compute_board,
)


# ---------------------------------------------------------------- 만들기 도구

def point(pid, text, speaker, type="의견", stance="찬성", target=None, anonymous=False,
          owner=None, due=None, reason=None, answer_to=None):
    message_id = pid.rsplit("-", 1)[0]
    return Point(id=pid, text=text, type=type, stance=stance, speaker=speaker,
                 evidence=(message_id,), anonymous=anonymous, reason=reason,
                 target=target, answer_to=answer_to, owner=owner, due=due)


def reaction(rid, speaker, kind="동의", reply_to=None, conf=0.9, anonymous=False):
    return Reaction(id=rid, speaker=speaker, reaction=kind, reply_to=reply_to,
                    reply_confidence=conf, anonymous=anonymous)


def cluster(cid, *pairs):
    return Cluster(cid, tuple(ClusterPoint(pid, relation) for pid, relation in pairs))


def ids(items):
    return [i.id for i in items]


def names(people):
    return [p.name for p in people]


# ---------------------------------------------------------------- v2 예시

def v2_example():
    points = [
        point("msg_4-1", "채팅 요약 필요", "가은", reason="AI 정리글이 김"),
        point("msg_4-2", "참여 독촉 필요", "가은", reason="조용한 사람이 많음"),
        point("msg_4-3", "질의응답 빼기", "가은", stance="반대", reason="비용이 큼"),
        point("msg_5-1", "요약 필수", "윤서", target="msg_4-1"),
        point("msg_5-2", "오해 감지 기능", "윤서", type="제안"),
    ]
    clusters = [cluster("c1", ("msg_4-1", "같음"), ("msg_5-1", "같음"))]
    reactions = [reaction("msg_6", "해원", reply_to="msg_5")]
    return points, clusters, reactions


def test_v2_example():
    points, clusters, reactions = v2_example()
    board = compute_board(points, clusters, reactions)

    assert ids(board.common) == ["c1"]
    assert names(board.common[0].people) == ["가은", "윤서"]
    assert board.common[0].text == "채팅 요약 필요"
    assert board.split == []
    assert ids(board.new) == ["solo:msg_4-2", "solo:msg_4-3", "solo:msg_5-2"]
    # msg_5에 포인트가 2개라 해원의 "ㅇㅋ"는 인원수에서 빠진다
    assert board.excluded_reactions == [ExcludedReaction("msg_6", "대상 메시지에 포인트 여러 개")]


def test_evidence_stays_inside_input():
    points, clusters, reactions = v2_example()
    board = compute_board(points, clusters, reactions)
    allowed = {e for p in points for e in p.evidence} | {r.id for r in reactions}
    for item in [*board.common, *board.split, *board.new, *board.need_check, *board.todos]:
        assert item.evidence
        assert set(item.evidence) <= allowed


def test_same_input_same_output():
    points, clusters, reactions = v2_example()
    assert compute_board(points, clusters, reactions) == compute_board(points, clusters, reactions)


# ---------------------------------------------------------------- 공통, 갈림, 새로움

def test_new_becomes_common_when_someone_agrees():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    assert ids(compute_board(points, [], []).new) == ["solo:msg_1-1"]

    board = compute_board(points, [], [reaction("msg_2", "지은", reply_to="msg_1")])
    assert ids(board.common) == ["solo:msg_1-1"]
    assert board.new == []
    assert names(board.common[0].people) == ["민수", "지은"]


def test_disagree_reaction_makes_split():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    board = compute_board(points, [], [reaction("msg_2", "지은", "반대", reply_to="msg_1")])
    assert ids(board.split) == ["solo:msg_1-1"]
    assert names(board.split[0].opponents) == ["지은"]
    assert board.common == [] and board.new == []


def test_opposite_relation_makes_split():
    points = [
        point("msg_1-1", "채팅 요약 필요", "가은"),
        point("msg_2-1", "요약은 필요 없음", "지호", stance="반대"),
    ]
    board = compute_board(points, [cluster("c1", ("msg_1-1", "같음"), ("msg_2-1", "반대"))], [])
    assert ids(board.split) == ["c1"]
    assert names(board.split[0].people) == ["가은"]
    assert names(board.split[0].opponents) == ["지호"]


def test_stance_against_target_point_makes_split():
    points = [
        point("msg_1-1", "홍대 가자", "민수", type="제안"),
        point("msg_2-1", "너무 멀어요", "지은", stance="반대", target="msg_1-1", reason="멀다"),
    ]
    board = compute_board(points, [], [])
    assert ids(board.split) == ["solo:msg_1-1"]
    assert names(board.split[0].opponents) == ["지은"]
    assert board.split[0].opponents[0].reason == "멀다"
    assert board.new == []  # 지은의 반대 포인트가 혼자 새로움으로 또 뜨지 않는다


def test_agree_on_opposing_point_joins_opposition():
    points = [
        point("msg_1-1", "채팅 요약 필요", "가은"),
        point("msg_2-1", "요약은 필요 없음", "지호", stance="반대"),
    ]
    clusters = [cluster("c1", ("msg_1-1", "같음"), ("msg_2-1", "반대"))]
    board = compute_board(points, clusters, [reaction("msg_3", "서연", reply_to="msg_2")])
    assert names(board.split[0].opponents) == ["지호", "서연"]


def test_same_person_counts_once():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    reactions = [
        reaction("msg_2", "민수", reply_to="msg_1"),  # 자기 의견에 동의
        reaction("msg_3", "지은", reply_to="msg_1"),
        reaction("msg_4", "지은", reply_to="msg_1"),
    ]
    board = compute_board(points, [], reactions)
    assert names(board.common[0].people) == ["민수", "지은"]


def test_person_who_changed_mind_follows_latest_message():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    agree_then_disagree = [
        reaction("msg_2", "지은", "동의", reply_to="msg_1"),
        reaction("msg_5", "지은", "반대", reply_to="msg_1"),
    ]
    board = compute_board(points, [], agree_then_disagree)
    assert names(board.split[0].opponents) == ["지은"]
    assert names(board.split[0].people) == ["민수"]

    disagree_then_agree = [
        reaction("msg_2", "지은", "반대", reply_to="msg_1"),
        reaction("msg_5", "지은", "동의", reply_to="msg_1"),
    ]
    board = compute_board(points, [], disagree_then_agree)
    assert names(board.common[0].people) == ["민수", "지은"]
    assert board.split == []

    # 입력 목록의 순서가 메시지 순서와 달라도 메시지 번호가 큰 쪽을 따른다
    board = compute_board(points, [], list(reversed(agree_then_disagree)))
    assert names(board.split[0].opponents) == ["지은"]
    board = compute_board(points, [], list(reversed(disagree_then_agree)))
    assert names(board.common[0].people) == ["민수", "지은"]


# ---------------------------------------------------------------- 반응 제외 기준

def test_unreliable_reactions_are_excluded():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    reactions = [
        reaction("msg_2", "지은", reply_to="msg_1", conf=0.3),
        reaction("msg_3", "하나", reply_to=None),
        reaction("msg_4", "보라", reply_to="msg_1", conf=None),
        reaction("msg_5", "다온", reply_to="msg_99"),
    ]
    board = compute_board(points, [], reactions)
    assert ids(board.new) == ["solo:msg_1-1"]
    assert [(e.id, e.why) for e in board.excluded_reactions] == [
        ("msg_2", "확신도 낮음"),
        ("msg_3", "대상 없음"),
        ("msg_4", "확신도 낮음"),
        ("msg_5", "대상 메시지에 포인트 없음"),
    ]


def test_confidence_threshold_comes_from_settings():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    reactions = [reaction("msg_2", "지은", reply_to="msg_1", conf=0.3)]
    board = compute_board(points, [], reactions, settings=BoardSettings(reaction_confidence_min=0.2))
    assert ids(board.common) == ["solo:msg_1-1"]


def test_confirm_reaction_is_ignored():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    board = compute_board(points, [], [reaction("msg_2", "지은", "확인", reply_to="msg_1")])
    assert ids(board.new) == ["solo:msg_1-1"]
    assert board.excluded_reactions == []


# ---------------------------------------------------------------- 익명

def test_anonymous_is_counted_and_labeled():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    reactions = [reaction("msg_2", "철수", reply_to="msg_1", anonymous=True)]
    board = compute_board(points, [], reactions)
    assert names(board.common[0].people) == ["민수", "익명 1"]
    assert "철수" not in str(board)  # 익명의 실제 이름은 나가지 않는다


def test_anonymous_can_be_left_out_by_setting():
    points = [point("msg_1-1", "홍대 가자", "민수", type="제안")]
    reactions = [reaction("msg_2", "철수", reply_to="msg_1", anonymous=True)]
    board = compute_board(points, [], reactions, settings=BoardSettings(count_anonymous=False))
    assert ids(board.new) == ["solo:msg_1-1"]
    assert names(board.new[0].people) == ["민수"]


def test_anonymous_labels_follow_first_appearance():
    points = [
        point("msg_1-1", "A안", "민수", type="제안", anonymous=True),
        point("msg_2-1", "B안", "지은", type="제안", anonymous=True),
    ]
    board = compute_board(points, [], [])
    assert names(board.new[0].people) == ["익명 1"]
    assert names(board.new[1].people) == ["익명 2"]


# ---------------------------------------------------------------- 확인 필요

def test_unanswered_question_needs_check():
    points = [point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연")]
    board = compute_board(points, [], [])
    assert ids(board.need_check) == ["msg_1-1"]
    assert board.need_check[0].target == "연"
    assert board.new == []  # 질문은 새로움에 안 들어간다


def test_answer_removes_question_from_need_check():
    points = [
        point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연"),
        point("msg_2-1", "가능해요", "연", type="정보", stance="없음", answer_to="msg_1-1"),
    ]
    board = compute_board(points, [], [])
    assert board.need_check == []
    assert board.new == []  # 답 포인트가 새로움에 또 뜨지 않는다


def test_askers_own_follow_up_is_not_an_answer():
    points = [
        point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연"),
        point("msg_2-1", "급하진 않아요", "지현", type="정보", stance="없음", answer_to="msg_1-1"),
    ]
    assert ids(compute_board(points, [], []).need_check) == ["msg_1-1"]


def test_answer_far_above_still_resolves_the_question():
    points = [
        point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연"),
        point("msg_2-1", "요약 필요", "가은"),
        point("msg_3-1", "독촉 필요", "윤서"),
        point("msg_9-1", "가능해요", "연", type="정보", stance="없음", answer_to="msg_1-1"),
    ]
    assert compute_board(points, [], []).need_check == []


def test_only_the_linked_question_is_resolved():
    points = [
        point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연"),
        point("msg_2-1", "비용은요?", "윤서", type="질문", stance="없음", target="전원"),
        point("msg_3-1", "가능해요", "연", type="정보", stance="없음", answer_to="msg_2-1"),
    ]
    assert ids(compute_board(points, [], []).need_check) == ["msg_1-1"]


def test_unknown_answer_to_is_ignored():
    points = [
        point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연"),
        point("msg_2-1", "가능해요", "연", type="정보", stance="없음", answer_to="msg_99-1"),
    ]
    assert ids(compute_board(points, [], []).need_check) == ["msg_1-1"]  # 없는 ID는 무시, 오류 없음


def test_target_alone_is_not_an_answer():
    # target은 주제 텍스트다. 질문 ID가 들어 있어도 답으로 치지 않는다 (답은 answer_to로만).
    points = [
        point("msg_1-1", "실시간으로 가능한가요?", "지현", type="질문", stance="없음", target="연"),
        point("msg_2-1", "가능해요", "연", type="정보", stance="없음", target="msg_1-1"),
    ]
    assert ids(compute_board(points, [], []).need_check) == ["msg_1-1"]


# ---------------------------------------------------------------- 할 일

def test_todo_point_goes_to_todos():
    points = [point("msg_1-1", "회의록 정리", "가은", type="할 일", stance="없음", owner="가은", due="2026-12-06")]
    board = compute_board(points, [], [])
    assert ids(board.todos) == ["msg_1-1"]
    assert (board.todos[0].owner, board.todos[0].due) == ("가은", "2026-12-06")
    assert board.new == []


def test_todo_without_owner_falls_back_to_speaker():
    points = [point("msg_1-1", "예약은 제가 할게요", "민수", type="할 일", stance="없음")]
    assert compute_board(points, [], []).todos[0].owner == "민수"


def test_request_accepted_by_recipient_becomes_todo():
    points = [point("msg_1-1", "피그마 확인", "유민", type="요청", stance="없음", target="가은", due="2026-12-01")]
    board = compute_board(points, [], [reaction("msg_2", "가은", reply_to="msg_1")])
    assert board.need_check == []
    assert [(t.owner, t.due) for t in board.todos] == [("가은", "2026-12-01")]


def test_request_stays_open_when_someone_else_agrees():
    points = [point("msg_1-1", "피그마 확인", "유민", type="요청", stance="없음", target="가은")]
    board = compute_board(points, [], [reaction("msg_2", "지현", reply_to="msg_1")])
    assert ids(board.need_check) == ["msg_1-1"]
    assert board.todos == []


def test_request_to_everyone_is_accepted_by_anyone_but_the_asker():
    points = [point("msg_1-1", "피그마 확인", "유민", type="요청", stance="없음")]
    own = compute_board(points, [], [reaction("msg_2", "유민", reply_to="msg_1")])
    assert ids(own.need_check) == ["msg_1-1"]  # 요청한 사람 본인의 동의는 수락이 아니다

    board = compute_board(points, [], [reaction("msg_2", "가은", reply_to="msg_1")])
    assert board.need_check == [] and [t.owner for t in board.todos] == ["가은"]


def test_request_with_target_everyone_is_accepted_by_anyone_but_the_asker():
    points = [point("msg_1-1", "피그마 확인", "유민", type="요청", stance="없음", target="전원")]
    own = compute_board(points, [], [reaction("msg_2", "유민", reply_to="msg_1")])
    assert ids(own.need_check) == ["msg_1-1"]

    board = compute_board(points, [], [reaction("msg_2", "가은", reply_to="msg_1")])
    assert board.need_check == [] and [t.owner for t in board.todos] == ["가은"]


def test_todo_point_answering_a_request_resolves_it():
    points = [
        point("msg_1-1", "피그마 확인", "유민", type="요청", stance="없음", target="가은"),
        point("msg_2-1", "제가 할게요", "가은", type="할 일", stance="없음", answer_to="msg_1-1", owner="가은"),
    ]
    board = compute_board(points, [], [])
    assert board.need_check == []
    assert ids(board.todos) == ["msg_2-1"]


def test_response_to_non_claim_point_falls_back_to_solo():
    points = [
        point("msg_1-1", "예약", "민수", type="할 일", stance="없음", owner="민수"),
        point("msg_2-1", "좋아요", "지은", target="msg_1-1"),
    ]
    board = compute_board(points, [], [])
    assert ids(board.todos) == ["msg_1-1"]
    assert ids(board.new) == ["solo:msg_2-1"]


# ---------------------------------------------------------------- 스키마

def v2_request_dict():
    return {
        "points": [
            {"id": "msg_4-1", "text": "채팅 요약 필요", "type": "의견", "stance": "찬성",
             "reason": "AI 정리글이 김", "evidence": ["msg_4"], "speaker": "가은"},
            {"id": "msg_5-1", "text": "요약 필수", "type": "의견", "stance": "찬성",
             "target": "msg_4-1", "evidence": ["msg_5"], "speaker": "윤서"},
            {"id": "msg_5-2", "text": "오해 감지 기능", "type": "제안", "stance": "찬성",
             "evidence": ["msg_5"], "speaker": "윤서", "anonymous": True},
        ],
        "clusters": [{"id": "c1", "points": [{"id": "msg_4-1", "relation": "같음"},
                                              {"id": "msg_5-1", "relation": "같음"}]}],
        "reactions": [{"id": "msg_6", "speaker": "해원", "reaction": "동의",
                       "reply_to": "msg_5", "reply_confidence": 0.9}],
    }


def test_request_to_response_round_trip():
    request = BoardRequest.model_validate(v2_request_dict())
    points, clusters, reactions = request.to_domain()
    board = compute_board(points, clusters, reactions)
    dumped = BoardResponse.from_domain(board).model_dump()

    assert set(dumped) == {"common", "split", "new", "need_check", "todos"}
    assert [i["id"] for i in dumped["common"]] == ["c1"]
    assert dumped["new"][0]["people"][0]["name"] == "익명 1"
    # 제외된 반응은 응답에는 없고 계산 결과에만 남는다 (평가용)
    assert board.excluded_reactions == [ExcludedReaction("msg_6", "대상 메시지에 포인트 여러 개")]


def test_answer_to_passes_through_the_schema():
    data = v2_request_dict()
    data["points"] += [
        {"id": "msg_7-1", "text": "가능한가요?", "type": "질문", "stance": "없음", "target": "전원",
         "evidence": ["msg_7"], "speaker": "윤서"},
        {"id": "msg_8-1", "text": "가능해요", "type": "정보", "stance": "없음", "answer_to": "msg_7-1",
         "evidence": ["msg_8"], "speaker": "연"},
    ]
    points, clusters, reactions = BoardRequest.model_validate(data).to_domain()
    assert {p.id: p.answer_to for p in points}["msg_8-1"] == "msg_7-1"
    assert "msg_7-1" not in ids(compute_board(points, clusters, reactions).need_check)


def test_request_rejects_unknown_values():
    data = v2_request_dict()
    data["points"][0]["type"] = "감탄"
    with pytest.raises(ValidationError):
        BoardRequest.model_validate(data)

    data = v2_request_dict()
    data["reactions"][0]["reaction"] = "내용 있음"
    with pytest.raises(ValidationError):
        BoardRequest.model_validate(data)
