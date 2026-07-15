Select M.title as Meeting_Title,
M.meeting_date as Meeting_Date,
M.public_url as Meeting_URL,
cou.name as Council_Name,
PE_6.event_value as Event,
P.canonical_name as Councillor,
P.person_uid as CouncillorUID,
PAR.name as Party
from meetings as M
left join committees as C
on M.committee_id = C.id
and M.council_id = C.council_id
left join person_events as PE_6
on M.committee_id = PE_6.committee_id
and M.council_id = PE_6.council_id
left join people as P
on PE_6.person_id = P.id
and PE_6.council_id = P.council_id
Left join councils as cou
on M.council_id = cou.id
left join person_events as PE_3
on P.id = PE_3.person_id 
and P.council_id = PE_3.council_id
left join parties as PAR
on PE_3.party_id = PAR.id
Where 
(PE_6.event_type_id = 6 
and PE_6.effective_from <= M.meeting_date and (PE_6.effective_to >= M.meeting_date or PE_6.effective_to is null))
or (PE_3.event_type_id = 3
and PE_3.effective_from <= M.meeting_date and (PE_3.effective_to >= M.meeting_date or PE_3.effective_to is null))

