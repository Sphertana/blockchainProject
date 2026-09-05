// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ClassLedger — one class's materials and grades on a private chain.
/// All access rules of the assignment are enforced here; the web app only mirrors them.
/// Reads are gated on msg.sender, which the gateway sets via `eth_call { from }`.
contract ClassLedger {
    enum Kind {
        LECTURE,
        LAB,
        EXAM,
        CORRECTION
    }

    struct Material {
        Kind kind;
        string title;
        string fileRef; // opaque path/id on the server disk, not the file itself
        bytes32 fileHash; // SHA-256 of the file, anchored for integrity
        uint64 examAt; // exam date (EXAM/CORRECTION only); availability = examAt + 24h
        bool hasPrev; // true if this entry is a revision of an earlier one
        uint256 prevId; // the revised entry (kept, never overwritten)
        uint64 createdAt;
    }

    uint64 public constant EXAM_DELAY = 24 hours;

    address public teacher;
    string public classDescription; // public
    string public classOrganization; // public

    Material[] private materials;
    mapping(address => bool) public isEnrolled;
    address[] private students;

    mapping(address => bool) private gradePublished;
    mapping(address => string) private grade; // readable only by its owner or the teacher

    event Enrolled(address indexed student);
    event MaterialAdded(uint256 indexed id, Kind kind, string title);
    event GradePublished(address indexed student); // never logs the grade value

    modifier onlyTeacher() {
        require(msg.sender == teacher, "not teacher");
        _;
    }

    constructor(string memory description, string memory organization) {
        teacher = msg.sender;
        classDescription = description;
        classOrganization = organization;
    }

    // --- teacher-only writes ---

    function setClassInfo(string calldata description, string calldata organization) external onlyTeacher {
        classDescription = description;
        classOrganization = organization;
    }

    function enroll(address student) external onlyTeacher {
        require(!isEnrolled[student], "already enrolled");
        isEnrolled[student] = true;
        students.push(student);
        emit Enrolled(student);
    }

    function addMaterial(
        Kind kind,
        string calldata title,
        string calldata fileRef,
        bytes32 fileHash,
        uint64 examAt,
        bool hasPrev,
        uint256 prevId
    ) external onlyTeacher returns (uint256 id) {
        if (kind == Kind.EXAM || kind == Kind.CORRECTION) {
            require(examAt > 0, "examAt required");
        }
        if (hasPrev) {
            require(prevId < materials.length, "bad prevId");
        }
        materials.push(
            Material({
                kind: kind,
                title: title,
                fileRef: fileRef,
                fileHash: fileHash,
                examAt: examAt,
                hasPrev: hasPrev,
                prevId: prevId,
                createdAt: uint64(block.timestamp)
            })
        );
        id = materials.length - 1;
        emit MaterialAdded(id, kind, title);
    }

    function publishGrade(address student, string calldata value) external onlyTeacher {
        require(isEnrolled[student], "not enrolled");
        grade[student] = value;
        gradePublished[student] = true;
        emit GradePublished(student);
    }

    // --- access-controlled reads (msg.sender = the calling user) ---

    function materialCount() external view returns (uint256) {
        return materials.length;
    }

    /// Rule engine: who may see a given material right now.
    function _visible(Material storage m) internal view returns (bool) {
        if (msg.sender == teacher) return true;
        if (!isEnrolled[msg.sender]) return false;
        if (m.kind == Kind.EXAM || m.kind == Kind.CORRECTION) {
            return block.timestamp >= uint256(m.examAt) + EXAM_DELAY;
        }
        return true; // lectures & labs: enrolled is enough
    }

    function canAccess(uint256 id) external view returns (bool) {
        require(id < materials.length, "bad id");
        return _visible(materials[id]);
    }

    /// Listing metadata for enrolled users; `accessible` reflects the 24h rule.
    function getMeta(uint256 id)
        external
        view
        returns (Kind kind, string memory title, uint64 examAt, bool hasPrev, uint256 prevId, bool accessible)
    {
        require(id < materials.length, "bad id");
        require(msg.sender == teacher || isEnrolled[msg.sender], "forbidden");
        Material storage m = materials[id];
        return (m.kind, m.title, m.examAt, m.hasPrev, m.prevId, _visible(m));
    }

    /// File reference + hash, only when the caller may actually access the file.
    function getFile(uint256 id) external view returns (string memory fileRef, bytes32 fileHash) {
        require(id < materials.length, "bad id");
        Material storage m = materials[id];
        require(_visible(m), "forbidden");
        return (m.fileRef, m.fileHash);
    }

    function myGrade() external view returns (bool published, string memory value) {
        return (gradePublished[msg.sender], gradePublished[msg.sender] ? grade[msg.sender] : "");
    }

    function gradeOf(address student) external view returns (bool published, string memory value) {
        require(msg.sender == teacher || msg.sender == student, "forbidden");
        return (gradePublished[student], gradePublished[student] ? grade[student] : "");
    }

    function studentCount() external view returns (uint256) {
        return students.length;
    }

    function studentAt(uint256 i) external view returns (address) {
        require(msg.sender == teacher, "forbidden");
        require(i < students.length, "bad index");
        return students[i];
    }
}
