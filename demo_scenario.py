"""API-free deterministic Loom replay, isolated from the normal workflow."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from config import ensure_run_directory
from evaluation import calculate_diagnostics
from models import GateResult, SemanticEvaluation, StaticEvaluation

DEMO_TRIGGER_TOPIC = "How does RAG help AI answer with facts?"

def deterministic_demo_enabled(topic: str) -> bool:
    return os.getenv("ENABLE_DETERMINISTIC_DEMO", "").lower() == "true" and topic.strip() == DEMO_TRIGGER_TOPIC

def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")

def _lesson(technical: bool) -> str:
    opening = ("RAG is an inference-time orchestration pattern that combines parametric knowledge with non-parametric retrieval. Large language models use parametric memory. RAG combines embeddings, semantic similarity, vector search and context windows before generation." if technical else "Imagine a college AI assistant answering a scholarship question. The rules changed last month. A better assistant opens the latest document, finds the relevant section, and only then answers. This simple search-first idea is RAG.")
    return f'''# How does RAG help AI answer with facts?

## Start with a simple problem

{opening}

## What is How does RAG help AI answer with facts?

RAG stands for Retrieval-Augmented Generation. It retrieves relevant information from an external knowledge source and lets a language model use that information while producing an answer.

## Why does it matter?

An LLM may not know a company's private policy, a product manual uploaded yesterday, or a college rule that changed after training. RAG keeps changing information outside the LLM and looks it up when needed.

## How does it work?

Documents are divided into smaller pieces called chunks. An embedding is a list of numbers that helps compare meaning. The system searches for relevant chunks, gives them to the model as context, and the model creates an answer. The simple flow is Question → Search → Find relevant information → Give it to the LLM → Answer.

Think of this as an open-book exam. The model is still responsible for writing a clear answer, but it is allowed to look at selected pages before it writes. The retrieved pages are not automatically true; they are simply the evidence chosen for this particular question. A useful RAG application records which pages were selected so a person can inspect them later.

The retrieval step has two jobs. First, it must find information that is related to the question. Second, it should avoid filling the prompt with unrelated text. Smaller chunks can make a specific answer easier to find, while chunks that are too small can lose important context. There is no single best chunk size for every document set, so teams test their choices using real questions.

When the selected chunks arrive, the application combines them with instructions such as “answer only from the supplied information” or “say when the documents do not contain the answer.” The LLM then reads this temporary context and generates a response. On the next question, the system can retrieve different chunks, so the answer can reflect a newly updated source without changing the model's trained weights.

## Step-by-step example

An employee asks, "How many casual leave days do I get?" The application searches the employee handbook, finds the leave-policy chunk, puts that information next to the question, and lets the model answer from the retrieved policy. The handbook can be updated without retraining the entire model. The same pattern supports customer-support assistants, company knowledge tools, developer documentation assistants, and research-document helpers.

Here is the same example in slow motion. The employee sends a question. The system converts the question into a form that can be compared with the handbook chunks. It ranks likely matches, selects the leave-policy passage, and passes that passage to the LLM. The answer can say, “The handbook says you receive these days,” instead of pretending the model remembered a policy by itself. If the handbook does not mention casual leave, a well-designed assistant should admit that it could not find the policy.

For a college assistant, the source might be an admissions notice rather than an employee handbook. A student could ask for the deadline for a scholarship form. The application retrieves the current notice, not an old social-media post, and the model explains the deadline in simple language. The same design is useful when facts change often, when an organization has private documents, or when users need an answer tied to a source they can verify.

## Important terms

**Chunk** means a smaller piece of a large document. **Embedding** means a numerical representation used to compare meaning. **Retrieval** means finding information relevant to a question. **Context** means information supplied to the LLM for the current answer. **Vector search** is a way to search numerical representations by similar meaning.

## Limitations

RAG is useful but not magic. If retrieval finds the wrong information, the LLM receives bad context. If a source document is wrong, RAG may repeat that mistake. The model can also misunderstand correctly retrieved information, so RAG improves grounding but does not guarantee perfect answers.

## Quick recap

- RAG lets an AI look up useful information before answering.
- It retrieves relevant document chunks and supplies them as context.
- Good sources and good retrieval both matter.

## Check your understanding

1. In your own words, why might an LLM need RAG?
2. What is a chunk, and why do we split long documents into chunks?
3. After relevant information is retrieved, what happens before the LLM generates its final answer?
'''

def _evaluation(failed: set[str]) -> SemanticEvaluation:
    names = {"R1":"Factual Accuracy","R2":"Essential Coverage","R3":"Beginner Accessibility","R4":"Jargon Explainability","R5":"Learning by Example","R6":"Teaching Flow","R7":"Appropriate Depth","R8":"Standalone & Complete"}
    details = {"R3":("The lesson is technically correct, but its opening assumes familiarity with concepts such as inference-time orchestration, parametric memory, embeddings, semantic similarity and context windows. This is too advanced for the defined zero-background learner.","RAG is an inference-time orchestration pattern that combines parametric knowledge with non-parametric retrieval.","Start with a familiar real-life problem and explain the simple 'look up information before answering' mental model before introducing technical architecture."),"R4":("Important technical terms are used before they are explained.","The lesson uses 'embedding', 'vector database', 'semantic similarity' and 'context window' before giving the learner plain-language meanings.","Define each essential technical term in simple language when it first appears. Keep the correct technical vocabulary, but introduce it only after the learner has the basic idea.")}
    return SemanticEvaluation(gates=[GateResult(gate_id=k,name=v,passed=k not in failed,reason=details.get(k,("Requirement met.","Core lesson evidence supports this gate.","No change needed."))[0],evidence=details.get(k,("Requirement met.","Core lesson evidence supports this gate.","No change needed."))[1],required_fix=details.get(k,("Requirement met.","Core lesson evidence supports this gate.","No change needed."))[2]) for k,v in names.items()])

def run_deterministic_demo(topic: str, run_id: str, event_sink: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    run = ensure_run_directory(run_id)
    sources = [{"candidate_id":f"CAND_{i:03d}","source_id":f"SRC_{i:03d}","title":title,"url":url,"domain":domain,"content":"Predefined demo evidence.","authority_type":authority,"selection_reason":reason} for i,(title,url,domain,authority,reason) in enumerate([("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks","https://arxiv.org/abs/2005.11401","arxiv.org","PRIMARY_RESEARCH","Foundational research source for Retrieval-Augmented Generation."),("Retrieval-Augmented Generation (RAG)","https://cloud.google.com/use-cases/retrieval-augmented-generation","cloud.google.com","OFFICIAL_TECHNICAL_DOCUMENTATION","Clear modern explanation of grounding generation with retrieved external information."),("Retrieval-Augmented Generation","https://www.pinecone.io/learn/retrieval-augmented-generation/","pinecone.io","ESTABLISHED_TECHNICAL_REFERENCE","Useful implementation-level explanation of retrieval, chunking, embeddings and vector search.")],1)]
    facts = [{"fact_id":f"FACT_{i:03d}","concept":"RAG","statement":s,"supported_by":["SRC_001","SRC_002"],"status":"supported","evidence":[{"source_id":"SRC_001","excerpt":s}]} for i,s in enumerate(["RAG stands for Retrieval-Augmented Generation.","RAG combines retrieval with generation using external information.","External knowledge is separate from trained weights.","Long documents are divided into chunks.","Embeddings are numerical representations of meaning.","Retrieval selects information relevant to a question.","Retrieved information becomes context before generation.","RAG does not guarantee a correct answer."],1)]
    lessons, evaluations = [_lesson(True),_lesson(False)], [_evaluation({"R3","R4"}),_evaluation(set())]
    statics=[]
    for i,lesson in enumerate(lessons):
        static=StaticEvaluation(passed=True,failures=[],missing_headings=[],learner_question_count=3,attempt_number=i,**calculate_diagnostics(lesson)); statics.append(static)
        (run/f"attempt_{i}.md").write_text(lesson,encoding="utf-8"); _write(run/f"static_evaluation_{i}.json",static.model_dump()); _write(run/f"evaluation_{i}.json",evaluations[i].model_dump())
    failure={"attempt":0,"failed_gates":[g.model_dump() for g in evaluations[0].gates if not g.passed]}
    _write(run/"failure_packet_0.json",failure); _write(run/"research_plan.json",{"canonical_topic":"Retrieval-Augmented Generation","learning_scope":["what RAG means","retrieval","chunking","embeddings","context augmentation","generation","limitations"],"search_queries":["Retrieval-Augmented Generation original paper","RAG official technical documentation","retrieval augmented generation embeddings retrieval documentation"]}); _write(run/"source_manifest.json",sources); _write(run/"canonical_facts.json",facts); (run/"knowledge_pack.md").write_text("# Demo Evidence Pack\n\n8 canonical facts.",encoding="utf-8"); (run/"final_lesson.md").write_text(lessons[1],encoding="utf-8")
    events=[]
    def add(status,title,detail="",attempt=None):
        item={"timestamp":datetime.now(timezone.utc).isoformat(),"stage":"deterministic_demo","status":status,"title":title,"detail":detail,"attempt":attempt}; events.append(item); event_sink and event_sink(item)
    for item in [("completed","Workflow started","Preparing research and grounded lesson generation.",None),("completed","Cross-run memory loaded","Existing learned guardrails loaded; demo memory writes are disabled.",None),("completed","Research plan created","3 search queries prepared.",None),("completed","Source discovery complete","12 candidate sources reviewed.",None),("completed","Authoritative sources selected","3 trusted sources selected.",None),("completed","Grounded knowledge built","8 canonical facts available.",None),("completed","Lesson plan created","9 beginner lesson sections planned.",None),("completed","Attempt 1 generated",f"{statics[0].word_count} words",0),("completed","Static checks completed","All deterministic checks passed.",0),("failed","Semantic evaluation completed","6 / 8 quality gates passed.",0),("failed","Attempt 1 rejected","R3 and R4 require a targeted revision.",0),("failed","R3 Beginner Accessibility","Opening is too technical for the target learner.",0),("failed","R4 Jargon Explained","Technical vocabulary appears before explanation.",0),("retry","Targeted revision started","Applying evaluator feedback for R3 and R4.",1),("completed","Attempt 2 generated",f"{statics[1].word_count} words",1),("completed","Static checks completed","All deterministic checks passed.",1),("completed","Semantic evaluation completed","8 / 8 quality gates passed.",1),("completed","Attempt 2 passed all hard gates","Static checks and all 8 semantic gates passed.",1),("completed","READY TO SHIP","Workflow complete.",None),("completed","Demo run complete","Persistent learning memory was not modified.",None)]: add(*item)
    _write(run/"events.json",events); _write(run/"rejection_log.json",[{"attempt":0,"static_failures":[],"failed_gates":failure["failed_gates"]}]); _write(run/"loaded_guardrails.json",[]); _write(run/"memory_update.json",{"skipped":"Deterministic demo: persistent memory writes disabled."})
    attempts=[{"attempt_number":i,"lesson_path":str(run/f"attempt_{i}.md"),"prompt_kind":"initial" if i==0 else "revision","revision_feedback":failure if i==0 else None,"static_evaluation":statics[i].model_dump(),"semantic_evaluation":evaluations[i].model_dump()} for i in range(2)]
    _write(run/"run_summary.json",{"run_id":run_id,"topic":topic,"trigger_topic":DEMO_TRIGGER_TOPIC,"mode":"deterministic_demo","memory_write_enabled":False,"final_status":"READY_TO_SHIP","attempt_count":2,"attempts":attempts})
    return {"topic":topic,"run_id":run_id,"final_status":"READY_TO_SHIP","attempt_history":[],"rejection_log":[]}
